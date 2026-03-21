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

BOT_TOKEN  = os.environ["BOT_TOKEN"]
CHAT_ID    = os.environ["CHAT_ID"]
GROQ_KEY   = os.environ["GROQ_KEY"]

PUBLISHED_FILE     = "published.json"
MAX_POSTS_PER_RUN  = 1       # 1 новость за запуск
FRESHNESS_HOURS    = 2       # не брать новости старше 2 часов
DELAY_BETWEEN_POSTS = 4      # секунды между постами (на случай если MAX > 1)

# ══════════════════════════════════════════
#  RSS ИСТОЧНИКИ
# ══════════════════════════════════════════

RSS_FEEDS = [
    # 🌍 Мировые новости
    ("BBC World",           "https://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters",             "https://feeds.reuters.com/reuters/topNews"),
    ("Al Jazeera",          "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Associated Press",    "https://feeds.feedburner.com/APNewsAlerts"),

    # 💻 Технологии и ИИ
    ("TechCrunch",          "https://techcrunch.com/feed/"),
    ("The Verge",           "https://www.theverge.com/rss/index.xml"),
    ("Hacker News",         "https://hnrss.org/frontpage"),
    ("Wired",               "https://www.wired.com/feed/rss"),
    ("Ars Technica",        "https://feeds.arstechnica.com/arstechnica/index"),
    ("MIT Tech Review",     "https://www.technologyreview.com/feed/"),

    # 💰 Бизнес и деньги
    ("Bloomberg Markets",   "https://feeds.bloomberg.com/markets/news.rss"),
    ("Fortune",             "https://fortune.com/feed/"),
    ("Business Insider",    "https://feeds.businessinsider.com/custom/all"),

    # 🔬 Наука
    ("Science Daily",       "https://www.sciencedaily.com/rss/all.xml"),
    ("NASA",                "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
    ("New Scientist",       "https://www.newscientist.com/feed/home/"),

    # 😄 Курьёзы и интересное
    ("Reddit World News",   "https://www.reddit.com/r/worldnews/.rss"),
    ("Today I Learned",     "https://www.reddit.com/r/todayilearned/.rss"),
    ("Reddit Interesting",  "https://www.reddit.com/r/InterestingAsHell/.rss"),
    ("Reddit Futurology",   "https://www.reddit.com/r/Futurology/.rss"),

    # 🎮 Игры и развлечения
    ("IGN",                 "https://feeds.ign.com/ign/all"),
    ("Kotaku",              "https://kotaku.com/rss"),
]

# ══════════════════════════════════════════
#  ПРОМПТ ДЛЯ ИИ
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
- Начни с 1-2 эмодзи
- Разговорный тон, без воды
- Пиши на русском языке
- Выбирай самую интересную и резонансную тему"""

USER_PROMPT_TEMPLATE = """Перепиши эту новость в стиле канала:

Заголовок: {title}
Краткое содержание: {summary}
Источник: {source}

Ответь ТОЛЬКО готовым текстом поста или словом SKIP. Никаких пояснений."""

# ══════════════════════════════════════════
#  РАБОТА С БАЗОЙ ОПУБЛИКОВАННЫХ
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
    # Держим только последние 1000 записей
    ids_list = list(ids)[-1000:]
    with open(PUBLISHED_FILE, "w") as f:
        json.dump(ids_list, f)

def make_url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def make_title_hash(title: str) -> str:
    # Хэш первых 5 слов заголовка — защита от одной темы с разных источников
    normalized = ' '.join(sorted(title.lower().split()[:5]))
    return "t_" + hashlib.md5(normalized.encode()).hexdigest()

# ══════════════════════════════════════════
#  ПОЛУЧЕНИЕ КАРТИНКИ ИЗ RSS
# ══════════════════════════════════════════

def get_image_from_entry(entry) -> str:
    # Способ 1: media:content
    media = entry.get("media_content", [])
    if media and media[0].get("url"):
        return media[0]["url"]

    # Способ 2: enclosures
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image"):
            return enc.get("href", "")

    # Способ 3: media:thumbnail
    thumbnail = entry.get("media_thumbnail", [])
    if thumbnail and thumbnail[0].get("url"):
        return thumbnail[0]["url"]

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

                # Пропускаем уже опубликованные (по URL и по заголовку)
                if url_hash in published_ids:
                    continue
                if title_hash in published_ids:
                    continue

                # Проверяем свежесть
                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                summary = entry.get("summary", entry.get("description", "")).strip()
                summary = re.sub(r'<[^>]+>', '', summary)[:600]

                if not title:
                    continue

                results.append({
                    "url_hash":   url_hash,
                    "title_hash": title_hash,
                    "title":      title,
                    "summary":    summary,
                    "link":       url,
                    "source":     source_name,
                    "image_url":  get_image_from_entry(entry),
                })

        except Exception as e:
            print(f"⚠️  Ошибка при чтении {source_name}: {e}")
            continue

    import random
    random.shuffle(results)
    return results[:MAX_POSTS_PER_RUN * 5]  # берём с запасом для фильтрации

# ══════════════════════════════════════════
#  ИИ-РЕРАЙТ (Groq)
# ══════════════════════════════════════════

def rewrite_with_ai(title: str, summary: str, source: str) -> str:
    prompt = USER_PROMPT_TEMPLATE.format(
        title=title,
        summary=summary if summary else "Нет описания",
        source=source
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
                "max_tokens": 300,
                "temperature": 0.7
            },
            timeout=30
        )

        if response.status_code != 200:
            print(f"⚠️  Groq ошибка {response.status_code}: {response.text[:200]}")
            return None

        text = response.json()["choices"][0]["message"]["content"].strip()

        # Если ИИ решил пропустить новость
        if text.upper().startswith("SKIP"):
            print("   ⏭️  ИИ пропустил (не интересно)")
            return None

        return text

    except Exception as e:
        print(f"⚠️  Ошибка ИИ: {e}")
        return None

# ══════════════════════════════════════════
#  ПУБЛИКАЦИЯ В TELEGRAM
# ══════════════════════════════════════════

def send_to_telegram(text: str, image_url: str = None) -> bool:
    # Инлайн кнопка "Подписаться"
    reply_markup = json.dumps({
        "inline_keyboard": [[
            {"text": "👉 Подписаться на канал", "url": "https://t.me/+vJDHO64MwXoxNjIy"}
        ]]
    })

    try:
        if image_url:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json={
                    "chat_id":      CHAT_ID,
                    "photo":        image_url,
                    "caption":      text,
                    "parse_mode":   "HTML",
                    "reply_markup": reply_markup,
                },
                timeout=15
            )
        else:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id":                  CHAT_ID,
                    "text":                     text,
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup":             reply_markup,
                },
                timeout=15
            )

        if response.status_code == 200:
            return True
        else:
            if image_url:
                print("   ⚠️  Фото не загрузилось, публикую без фото")
                return send_to_telegram(text, image_url=None)
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

        rewritten = rewrite_with_ai(item["title"], item["summary"], item["source"])

        if not rewritten:
            # Помечаем как просмотренное чтобы не возвращаться
            published.add(item["url_hash"])
            published.add(item["title_hash"])
            continue

        success = send_to_telegram(rewritten, item.get("image_url"))

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
