# morning.py — Доброе утро в 7:00 по Киеву
# Приветствие + погода в Киеве + главные темы дня

import feedparser
import requests
import os
import re
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
GROQ_KEY  = os.environ["GROQ_KEY"]

CITY = "Kyiv"  # Можно поменять на свой город

RSS_FEEDS = [
    ("BBC World",   "https://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters",     "https://feeds.reuters.com/reuters/topNews"),
    ("Al Jazeera",  "https://www.aljazeera.com/xml/rss/all.xml"),
]

MORNING_PROMPT = """Ты — редактор Telegram-канала «Слышь, новость».
Напиши утреннее приветствие для читателей канала.

Данные:
- Дата: {date}
- Погода: {weather}
- Главные новости утра: {news}

Формат строго такой:

🌅 <b>Доброе утро!</b>

{date_str}

🌤 <b>Погода:</b> {weather}

📌 <b>Главное сегодня:</b>
• [тема 1 — одно предложение]
• [тема 2 — одно предложение]
• [тема 3 — одно предложение]

[одна мотивирующая или остроумная фраза на день]

Пиши на русском, коротко и по-человечески."""


def get_weather() -> str:
    """Получает погоду через wttr.in — без API ключа."""
    try:
        response = requests.get(
            f"https://wttr.in/{CITY}?format=%C+%t+%h+влажность",
            timeout=10,
            headers={"User-Agent": "curl/7.68.0"}
        )
        if response.status_code == 200:
            return response.text.strip()
    except Exception as e:
        print(f"⚠️  Погода недоступна: {e}")
    return "данные недоступны"


def fetch_morning_news() -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    results = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                published_parsed = entry.get("published_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                title = entry.get("title", "").strip()
                if title:
                    results.append(title)
        except Exception as e:
            print(f"⚠️  Ошибка {source_name}: {e}")

    return results[:15]


def make_morning_post(weather: str, news: list) -> str:
    kyiv_time = datetime.now(timezone.utc) + timedelta(hours=2)
    date_str = kyiv_time.strftime("%A, %d %B %Y")

    # Переводим день недели и месяц на русский
    days = {"Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда",
            "Thursday": "Четверг", "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"}
    months = {"January": "января", "February": "февраля", "March": "марта", "April": "апреля",
              "May": "мая", "June": "июня", "July": "июля", "August": "августа",
              "September": "сентября", "October": "октября", "November": "ноября", "December": "декабря"}

    for en, ru in {**days, **months}.items():
        date_str = date_str.replace(en, ru)

    news_text = "\n".join(f"- {n}" for n in news[:10])
    prompt = MORNING_PROMPT.format(
        date=date_str,
        date_str=date_str,
        weather=weather,
        news=news_text
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
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.8
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️  Ошибка ИИ: {e}")
    return None


def send_message(text: str):
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
    print(f"🌅 Доброе утро | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    weather = get_weather()
    print(f"🌤 Погода: {weather}")

    news = fetch_morning_news()
    print(f"📰 Новостей: {len(news)}")

    post = make_morning_post(weather, news)
    if not post:
        print("❌ ИИ не ответил")
        return

    send_message(post)
    print("✅ Доброе утро опубликовано!")


if __name__ == "__main__":
    main()
