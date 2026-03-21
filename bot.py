# bot.py — Автоматический новостной бот «Слышь, новость»
# Запускается через GitHub Actions каждые 10 минут

import feedparser
import requests
import json
import os
import hashlib
import time
import re
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ══════════════════════════════════════════

BOT_TOKEN     = os.environ["BOT_TOKEN"]
CHAT_ID       = os.environ["CHAT_ID"]
GROQ_KEY      = os.environ["GROQ_KEY"]
UNSPLASH_KEY  = os.environ.get("UNSPLASH_KEY", "")  # опционально

PUBLISHED_FILE      = "published.json"
MAX_POSTS_PER_RUN   = 1
FRESHNESS_HOURS     = 2
DELAY_BETWEEN_POSTS = 4

QUIET_HOUR_START = 23
QUIET_HOUR_END   = 7

ALLOWED_EMOJIS = "❤️ 👍 👎 🔥 😁 😍 😱 🤬 😢 🎉 💩 🕊 🤡 ❤‍🔥 🏆 😭 💘"

# ══════════════════════════════════════════
#  RSS ИСТОЧНИКИ
# ══════════════════════════════════════════

RSS_FEEDS = [
    # Мировые новости
    ("BBC World",           "https://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters",             "https://feeds.reuters.com/reuters/topNews"),
    ("Al Jazeera",          "https://www.aljazeera.com/xml/rss/all.xml"),
    # Технологии и ИИ
    ("TechCrunch",          "https://techcrunch.com/feed/"),
    ("The Verge",           "https://www.theverge.com/rss/index.xml"),
    ("Hacker News",         "https://hnrss.org/frontpage"),
    ("Wired",               "https://www.wired.com/feed/rss"),
    ("Ars Technica",        "https://feeds.arstechnica.com/arstechnica/index"),
    ("MIT Tech Review",     "https://www.technologyreview.com/feed/"),
    # Бизнес
    ("Bloomberg Markets",   "https://feeds.bloomberg.com/markets/news.rss"),
    ("Fortune",             "https://fortune.com/feed/"),
    # Наука
    ("Science Daily",       "https://www.sciencedaily.com/rss/all.xml"),
    ("NASA",                "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
    # Курьёзы
    ("Reddit World News",   "https://www.reddit.com/r/worldnews/.rss"),
    ("Today I Learned",     "https://www.reddit.com/r/todayilearned/.rss"),
    ("Reddit Futurology",   "https://www.reddit.com/r/Futurology/.rss"),
]

# ══════════════════════════════════════════
#  ПРОМПТЫ ДЛЯ ИИ
# ══════════════════════════════════════════

SYSTEM_PROMPT = """Ты — редактор Telegram-канала «Слышь, новость».
Твоя задача: СНАЧАЛА оценить новость, потом написать пост.

ФИЛЬТР — публикуй только если новость попадает хотя бы в одну категорию:
✅ Технологии, ИИ, стартапы, гаджеты
✅ Деньги, бизнес, экономика
✅ Необычное, курьёзное, удивительное
✅ Мировая политика (крупные события)
✅ Наука и открытия

ИГНОРИРУЙ:
❌ Спорт (кроме скандалов)
❌ Светские новости, знаменитости
❌ Местные новости без мирового значения
❌ Реклама и PR-статьи

Если новость не проходит фильтр — ответь ТОЛЬКО одним словом: SKIP

Если проходит — напиши пост в стиле умного друга:
- 2-4 предложения
- Начни ТОЛЬКО с 1 эмодзи, соответствующего теме
- Разговорный тон, без воды
- Пиши на русском языке"""

USER_PROMPT_TEMPLATE = """Перепиши новость в стиле канала:

Заголовок: {title}
Краткое содержание: {summary}
Источник: {source}

Ответь строго в формате (четыре строки):
ТЕКСТ: [текст поста 2-4 предложения с эмодзи]
ФОТО: [1-2 слова на английском для поиска фото, отражающих суть новости]
РЕАКЦИЯ1: [эмодзи] — [короткий текст реакции от лица читателя]
РЕАКЦИЯ2: [эмодзи] — [короткий текст реакции от лица читателя]

Для реакций используй ТОЛЬКО эти эмодзи:
{allowed_emojis}

Примеры:
ТЕКСТ: 🔥 Что-то произошло...
ФОТО: space rocket
РЕАКЦИЯ1: 😱 — не может быть
РЕАКЦИЯ2: 🔥 — это топ

Если новость не интересна — ответь: SKIP"""

# ══════════════════════════════════════════
#  ТИХИЕ ЧАСЫ
# ══════════════════════════════════════════

def is_quiet_hours() -> bool:
    kyiv_offset = timedelta(hours=2)
    kyiv_time = datetime.now(timezone.utc) + kyiv_offset
    hour = kyiv_time.hour
    return hour >= QUIET_HOUR_START or hour < QUIET_HOUR_END

# ══════════════════════════════════════════
#  БАЗА ОПУБЛИКОВАННЫХ
# ══════════════════════════════════════════

def load_published() -> set:
    if os.path.exists(PUBLISHED_FILE):
        try:
            with open(PUBLISHED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_published(ids: set):
    with open(PUBLISHED_FILE, "w") as f:
        json.dump(list(ids)[-1000:], f)


def make_url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def make_title_hash(title: str) -> str:
    normalized = ' '.join(sorted(title.lower().split()[:5]))
    return "t_" + hashlib.md5(normalized.encode()).hexdigest()

# ══════════════════════════════════════════
#  ФОТО: RSS или Unsplash
# ══════════════════════════════════════════

def get_image_from_entry(entry) -> str:
    """Берёт фото из RSS если есть."""
    media = entry.get("media_content", [])
    if media and media[0].get("url"):
        return media[0]["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image"):
            return enc.get("href", "")
    thumbnail = entry.get("media_thumbnail", [])
    if thumbnail and thumbnail[0].get("url"):
        return thumbnail[0]["url"]
    return None


def get_unsplash_photo(query: str) -> str:
    """Ищет красивое фото на Unsplash по запросу."""
    if not UNSPLASH_KEY or not query:
        return None
    try:
        response = requests.get(
            "https://api.unsplash.com/photos/random",
            params={
                "query": query,
                "orientation": "landscape",
                "content_filter": "high"
            },
            headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return data["urls"]["regular"]
    except Exception as e:
        print(f"⚠️  Unsplash ошибка: {e}")
    return None

# ══════════════════════════════════════════
#  ПАРСИНГ RSS
# ══════════════════════════════════════════

def fetch_fresh_news(published_ids: set) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS)
    results = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:15]:
                url = entry.get("link", "")
                if not url:
                    continue

                url_hash   = make_url_hash(url)
                title      = entry.get("title", "").strip()
                title_hash = make_title_hash(title)

                if url_hash in published_ids or title_hash in published_ids:
                    continue

                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                summary = re.sub(
                    r'<[^>]+>', '',
                    entry.get("summary", entry.get("description", "")).strip()
                )[:600]

                if not title:
                    continue

                results.append({
                    "url_hash":   url_hash,
                    "title_hash": title_hash,
                    "title":      title,
                    "summary":    summary,
                    "link":       url,
                    "source":     source_name,
                    "rss_image":  get_image_from_entry(entry),
                })

        except Exception as e:
            print(f"⚠️  Ошибка при чтении {source_name}: {e}")
            continue

    import random
    random.shuffle(results)
    return results[:MAX_POSTS_PER_RUN * 5]

# ══════════════════════════════════════════
#  ИИ-РЕРАЙТ (Groq)
# ══════════════════════════════════════════

def rewrite_with_ai(title: str, summary: str, source: str):
    prompt = USER_PROMPT_TEMPLATE.format(
        title=title,
        summary=summary if summary else "Нет описания",
        source=source,
        allowed_emojis=ALLOWED_EMOJIS
    )
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt}
                ],
                "max_tokens": 350,
                "temperature": 0.7
            },
            timeout=30
        )

        if response.status_code != 200:
            print(f"⚠️  Groq ошибка {response.status_code}: {response.text[:200]}")
            return None, None, None

        text = response.json()["choices"][0]["message"]["content"].strip()

        if text.upper().startswith("SKIP"):
            print("   ⏭️  ИИ пропустил (не интересно)")
            return None, None, None

        post_text = ""
        photo_query = ""
        reakciya1 = ""
        reakciya2 = ""

        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("ТЕКСТ:"):
                post_text = line.replace("ТЕКСТ:", "").strip()
            elif line.startswith("ФОТО:"):
                photo_query = line.replace("ФОТО:", "").strip()
            elif line.startswith("РЕАКЦИЯ1:"):
                reakciya1 = line.replace("РЕАКЦИЯ1:", "").strip()
            elif line.startswith("РЕАКЦИЯ2:"):
                reakciya2 = line.replace("РЕАКЦИЯ2:", "").strip()

        if not post_text:
            post_text = text

        reactions = ""
        if reakciya1 or reakciya2:
            reactions = "\n\n" + reakciya1
            if reakciya2:
                reactions += "\n" + reakciya2

        return post_text, reactions, photo_query

    except Exception as e:
        print(f"⚠️  Ошибка ИИ: {e}")
        return None, None, None

# ══════════════════════════════════════════
#  ПУБЛИКАЦИЯ В TELEGRAM
# ══════════════════════════════════════════

def send_to_telegram(text: str, image_url: str = None, reactions: str = "") -> bool:
    full_text = text + reactions + "\n\n<a href='https://t.me/+vJDHO64MwXoxNjIy'>👉 Слышь, новость. Подписаться</a>"

    try:
        if image_url:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json={
                    "chat_id":    CHAT_ID,
                    "photo":      image_url,
                    "caption":    full_text,
                    "parse_mode": "HTML",
                },
                timeout=15
            )
        else:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id":                  CHAT_ID,
                    "text":                     full_text,
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15
            )

        if response.status_code == 200:
            return True
        else:
            if image_url:
                print("   ⚠️  Фото не загрузилось, публикую без фото")
                return send_to_telegram(text, image_url=None, reactions=reactions)
            error = response.json().get("description", "Неизвестная ошибка")
            print(f"❌ Telegram ошибка: {error}")
            return False

    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False

# ══════════════════════════════════════════
#  ГЛАВНАЯ ФУНКЦИЯ
# ══════════════════════════════════════════

def main():
    print(f"🚀 Запуск бота | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if is_quiet_hours():
        print("🌙 Тихие часы (23:00–07:00 по Киеву). Пропускаем.")
        return

    published = load_published()
    print(f"📚 В базе: {len(published)} записей")

    news_items = fetch_fresh_news(published)
    print(f"📰 Найдено новых: {len(news_items)}")

    if not news_items:
        print("✅ Новых новостей нет. Завершаем.")
        return

    published_count = 0

    for item in news_items:
        if published_count >= MAX_POSTS_PER_RUN:
            break

        print(f"\n🔄 Обрабатываю: {item['title'][:60]}...")

        post_text, reactions, photo_query = rewrite_with_ai(
            item["title"], item["summary"], item["source"]
        )

        if not post_text:
            published.add(item["url_hash"])
            published.add(item["title_hash"])
            continue

        # Выбираем фото: сначала RSS, потом Unsplash
        image_url = item.get("rss_image")
        if not image_url and photo_query and UNSPLASH_KEY:
            print(f"   🖼️  Ищу фото на Unsplash: {photo_query}")
            image_url = get_unsplash_photo(photo_query)
            if image_url:
                print(f"   ✅ Фото найдено")
            else:
                print(f"   ⚠️  Фото не найдено, публикую без фото")

        success = send_to_telegram(post_text, image_url, reactions or "")

        if success:
            published.add(item["url_hash"])
            published.add(item["title_hash"])
            published_count += 1
            print(f"   ✅ Опубликовано ({published_count}/{MAX_POSTS_PER_RUN})")
            if published_count < MAX_POSTS_PER_RUN:
                time.sleep(DELAY_BETWEEN_POSTS)
        else:
            print("   ❌ Не удалось опубликовать")

    save_published(published)
    print(f"\n🏁 Готово. Опубликовано: {published_count} постов.")


if __name__ == "__main__":
    main()
