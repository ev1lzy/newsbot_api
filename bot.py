# bot.py — Автоматический новостной бот «Что случилось»
# Запускается через GitHub Actions каждые 30 минут

import feedparser
import requests
import json
import os
import hashlib
import time
from datetime import datetime, timezone, timedelta

# ══════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ══════════════════════════════════════════

BOT_TOKEN      = os.environ["BOT_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
GROQ_KEY = os.environ["GROQ_KEY"]

PUBLISHED_FILE = "published.json"
MAX_POSTS_PER_RUN = 4        # сколько постов максимум за один запуск
FRESHNESS_HOURS = 2          # не брать новости старше N часов
DELAY_BETWEEN_POSTS = 4      # секунды между постами (антиспам)

# ══════════════════════════════════════════
#  RSS ИСТОЧНИКИ
# ══════════════════════════════════════════

RSS_FEEDS = [
    # Мировые новости
    ("BBC World",     "https://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters",       "https://feeds.reuters.com/reuters/topNews"),
    # Tech
    ("Hacker News",   "https://hnrss.org/frontpage"),
    ("TechCrunch",    "https://techcrunch.com/feed/"),
    ("The Verge",     "https://www.theverge.com/rss/index.xml"),
    # Интересное
    ("Reddit World",  "https://www.reddit.com/r/worldnews/.rss"),
    ("Today I Learned", "https://www.reddit.com/r/todayilearned/.rss"),
]

# ══════════════════════════════════════════
#  ПРОМПТ ДЛЯ ИИ (стиль «Что случилось»)
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

Если новость не проходит фильтр — ответь словом: SKIP

Если проходит — напиши пост в стиле умного друга:
- 2-4 предложения
- Начни с 1-2 эмодзи
- Разговорный тон, без воды
- Пиши на русском языке"""

USER_PROMPT_TEMPLATE = """Перепиши эту новость в стиле канала:

Заголовок: {title}
Краткое содержание: {summary}
Источник: {source}

Ответь ТОЛЬКО готовым текстом поста. Никаких пояснений."""

# ══════════════════════════════════════════
#  РАБОТА С БАЗОЙ ОПУБЛИКОВАННЫХ
# ══════════════════════════════════════════

def load_published() -> set:
    """Загружает хэши уже опубликованных новостей."""
    if os.path.exists(PUBLISHED_FILE):
        try:
            with open(PUBLISHED_FILE, "r") as f:
                data = json.load(f)
                return set(data)
        except (json.JSONDecodeError, IOError):
            return set()
    return set()

def save_published(ids: set):
    """Сохраняет хэши. Держим только последние 500 — чтобы файл не рос бесконечно."""
    ids_list = list(ids)[-500:]
    with open(PUBLISHED_FILE, "w") as f:
        json.dump(ids_list, f)

def make_hash(url: str) -> str:
    """Создаёт уникальный ID новости по URL."""
    return hashlib.md5(url.encode()).hexdigest()

# ══════════════════════════════════════════
#  ПАРСИНГ RSS
# ══════════════════════════════════════════

def fetch_fresh_news(published_ids: set) -> list:
    """
    Обходит все RSS-ленты, возвращает список новых свежих новостей.
    Каждый элемент: {'id', 'title', 'summary', 'link', 'source'}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS)
    results = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:15]:  # смотрим последние 15 записей
                url = entry.get("link", "")
                if not url:
                    continue

                uid = make_hash(url)
                if uid in published_ids:
                    continue  # уже публиковали

                # Проверяем свежесть
                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue  # слишком старая

                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()

                # Убираем HTML-теги из summary
                import re
                summary = re.sub(r'<[^>]+>', '', summary)[:600]

                if not title:
                    continue

                results.append({
    "id": uid,
    "title": title,
    "summary": summary,
    "link": url,
    "source": source_name,
    "image_url": get_image_from_entry(entry)
})

        except Exception as e:
            print(f"⚠️  Ошибка при чтении {source_name}: {e}")
            continue

    # Перемешиваем немного для разнообразия источников
    import random
    random.shuffle(results)
    
    return results[:MAX_POSTS_PER_RUN * 2]  # берём с запасом

# ══════════════════════════════════════════
#  ИИ-РЕРАЙТ (OpenRouter)
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
                    {"role": "user", "content": prompt}
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
        if text.upper().startswith("SKIP"):
            return None
        return text
    except Exception as e:
        print(f"⚠️  Ошибка ИИ: {e}")
        return None

# ══════════════════════════════════════════
#  ПУБЛИКАЦИЯ В TELEGRAM
# ══════════════════════════════════════════

def get_image_from_entry(entry) -> str:
    """Пытается достать URL картинки из RSS-записи."""
    # Способ 1: media:content
    media = entry.get("media_content", [])
    if media and media[0].get("url"):
        return media[0]["url"]
    
    # Способ 2: enclosures (вложения)
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("image"):
            return enc.get("href", "")
    
    # Способ 3: media:thumbnail
    thumbnail = entry.get("media_thumbnail", [])
    if thumbnail and thumbnail[0].get("url"):
        return thumbnail[0]["url"]

    return None


def send_to_telegram(text: str, image_url: str = None) -> bool:
    """Публикует пост в Telegram — с фото если есть, без ссылки."""
    try:
        if image_url:
            # Отправляем фото с текстом как подписью
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                json={
                    "chat_id": CHAT_ID,
                    "photo": image_url,
                    "caption": text,
                    "parse_mode": "HTML",
                },
                timeout=15
            )
        else:
            # Без фото — просто текст
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15
            )

        if response.status_code == 200:
            return True
        else:
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
    
    # 1. Загружаем уже опубликованные
    published = load_published()
    print(f"📚 В базе: {len(published)} опубликованных новостей")

    # 2. Парсим свежие новости
    news_items = fetch_fresh_news(published)
    print(f"📰 Найдено новых: {len(news_items)}")

    if not news_items:
        print("✅ Новых новостей нет. Завершаем.")
        return

    # 3. Обрабатываем и публикуем
    published_count = 0

    for item in news_items:
        if published_count >= MAX_POSTS_PER_RUN:
            break

        print(f"\n🔄 Обрабатываю: {item['title'][:60]}...")

        # ИИ-рерайт
        rewritten = rewrite_with_ai(item["title"], item["summary"], item["source"])
        
        if not rewritten:
            print("   ⚠️  Пропускаю (ИИ не ответил)")
            continue

        # Публикуем
        success = send_to_telegram(rewritten, item.get("image_url"))
        
        if success:
            published.add(item["id"])
            published_count += 1
            print(f"   ✅ Опубликовано ({published_count}/{MAX_POSTS_PER_RUN})")
            
            # Задержка между постами
            if published_count < MAX_POSTS_PER_RUN:
                time.sleep(8)  # пауза между запросами к ИИ
        else:
            print("   ❌ Не удалось опубликовать")

    # 4. Сохраняем базу
    save_published(published)
    print(f"\n🏁 Готово. Опубликовано: {published_count} постов.")

if __name__ == "__main__":
    main()