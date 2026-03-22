# digest.py — Дайджест дня в 20:00 по Киеву
# ИИ выбирает топ-3 новости за день и публикует одним постом

import feedparser
import requests
import json
import os
import re
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
GROQ_KEY  = os.environ["GROQ_KEY"]

RSS_FEEDS = [
    ("BBC World",         "https://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters",           "https://feeds.reuters.com/reuters/topNews"),
    ("TechCrunch",        "https://techcrunch.com/feed/"),
    ("The Verge",         "https://www.theverge.com/rss/index.xml"),
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("Science Daily",     "https://www.sciencedaily.com/rss/all.xml"),
    ("Al Jazeera",        "https://www.aljazeera.com/xml/rss/all.xml"),
]

DIGEST_PROMPT = """Ты — редактор Telegram-канала «Слышь, новость».
Тебе дан список новостей за сегодня. Выбери ТОП-3 самые важные и интересные.

Напиши дайджест строго в формате:

🗞 <b>Дайджест дня</b>

1️⃣ [заголовок новости 1]
[2-3 предложения о ней]

2️⃣ [заголовок новости 2]
[2-3 предложения о ней]

3️⃣ [заголовок новости 3]
[2-3 предложения о ней]

Пиши на русском языке. Стиль — умный друг, коротко и по делу."""


def fetch_todays_news() -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    results = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                title   = entry.get("title", "").strip()
                summary = re.sub(r'<[^>]+>', '', entry.get("summary", "").strip())[:300]

                if title:
                    results.append(f"- {title}: {summary}")
        except Exception as e:
            print(f"⚠️  Ошибка {source_name}: {e}")

    return results[:30]


def make_digest(news_list: list) -> str:
    news_text = "\n".join(news_list)
    prompt = f"{DIGEST_PROMPT}\n\nНовости за сегодня:\n{news_text}"

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.7
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️  Ошибка ИИ: {e}")
    return None


def send_digest(text: str):
    full_text = text + "\n\n<a href='https://t.me/+vJDHO64MwXoxNjIy'>👉 Слышь, новость. Подписаться</a>"
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id":                  CHAT_ID,
            "text":                     full_text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15
    )


def main():
    print(f"📋 Дайджест дня | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    news = fetch_todays_news()
    print(f"📰 Собрано новостей: {len(news)}")

    if not news:
        print("❌ Нет новостей за день")
        return

    digest = make_digest(news)
    if not digest:
        print("❌ ИИ не ответил")
        return

    send_digest(digest)
    print("✅ Дайджест опубликован!")


if __name__ == "__main__":
    main()