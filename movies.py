# movies.py — Пятничный топ фильмов
# Каждую пятницу в 18:00 по Киеву публикует топ-5 фильмов по жанру
# Жанр меняется каждую неделю чтобы не повторяться

import requests
import os
import json
import random
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = os.environ["CHAT_ID"]
GROQ_KEY     = os.environ["GROQ_KEY"]
UNSPLASH_KEY = os.environ.get("UNSPLASH_KEY", "")

# Жанры — чередуются каждую неделю
GENRES = [
    ("комедии",          "comedy",      "😂"),
    ("триллеры",         "thriller",    "😱"),
    ("драмы",            "drama",       "🎭"),
    ("фантастика",       "sci-fi",      "🚀"),
    ("боевики",          "action",      "💥"),
    ("криминал",         "crime",       "🔍"),
    ("анимация",         "animation",   "🎨"),
    ("документальные",   "documentary", "🎬"),
]

# IMDb жанровые страницы
IMDB_GENRE_URLS = {
    "comedy":      "https://www.imdb.com/search/title/?genres=comedy&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "thriller":    "https://www.imdb.com/search/title/?genres=thriller&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "drama":       "https://www.imdb.com/search/title/?genres=drama&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "sci-fi":      "https://www.imdb.com/search/title/?genres=sci-fi&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "action":      "https://www.imdb.com/search/title/?genres=action&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "crime":       "https://www.imdb.com/search/title/?genres=crime&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "animation":   "https://www.imdb.com/search/title/?genres=animation&sort=user_rating,desc&num_votes=50000,&title_type=movie",
    "documentary": "https://www.imdb.com/search/title/?genres=documentary&sort=user_rating,desc&num_votes=10000,&title_type=movie",
}

MOVIES_PROMPT = """Ты — редактор Telegram-канала «Слышь, новость».
Напиши пятничный пост про топ-5 фильмов жанра «{genre_ru}».

Список фильмов:
{movies_list}

Формат строго такой:

🎬 <b>Пятничный топ: {genre_emoji} {genre_ru} на вечер</b>

[одна фраза-затравка почему стоит смотреть этот жанр]

{numbered_list}

[короткая итоговая фраза — пожелание хорошего вечера]

Для каждого фильма напиши:
[номер][эмодзи] <b>Название</b> ([год]) — ⭐ [рейтинг]
[одно предложение почему стоит посмотреть, без спойлеров]

Пиши на русском языке, живо и с характером."""


def get_current_genre():
    """Выбирает жанр на основе номера недели — каждую неделю новый."""
    week_number = datetime.now(timezone.utc).isocalendar()[1]
    return GENRES[week_number % len(GENRES)]


def fetch_imdb_movies(genre_en: str) -> list:
    """Парсит топ фильмов с IMDb по жанру."""
    url = IMDB_GENRE_URLS.get(genre_en)
    if not url:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"⚠️  IMDb ответил {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        movies = []

        # Новый формат IMDb
        items = soup.select(".ipc-metadata-list-summary-item")[:10]

        for item in items:
            try:
                title_el = item.select_one("h3.ipc-title__text")
                title = title_el.text.strip() if title_el else ""
                # Убираем номер в начале (например "1. ")
                if title and title[0].isdigit():
                    title = title.split(". ", 1)[-1]

                year_el = item.select_one(".dli-title-metadata-item")
                year = year_el.text.strip() if year_el else ""

                rating_el = item.select_one(".ipc-rating-star--rating")
                rating = rating_el.text.strip() if rating_el else "N/A"

                if title:
                    movies.append({
                        "title":  title,
                        "year":   year,
                        "rating": rating,
                    })
            except Exception:
                continue

        return movies[:8]

    except Exception as e:
        print(f"⚠️  Ошибка парсинга IMDb: {e}")
        return []


def make_movies_post(genre_ru: str, genre_en: str, genre_emoji: str, movies: list) -> str:
    if not movies:
        return None

    movies_list = "\n".join(
        f"{i+1}. {m['title']} ({m['year']}) — ⭐ {m['rating']}"
        for i, m in enumerate(movies[:5])
    )

    prompt = MOVIES_PROMPT.format(
        genre_ru=genre_ru,
        genre_en=genre_en,
        genre_emoji=genre_emoji,
        movies_list=movies_list,
        numbered_list="[ИИ заполняет список]"
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
                "max_tokens": 700,
                "temperature": 0.8
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️  Ошибка ИИ: {e}")
    return None


def get_unsplash_photo(query: str) -> str:
    if not UNSPLASH_KEY:
        return None
    try:
        response = requests.get(
            "https://api.unsplash.com/photos/random",
            params={"query": query, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()["urls"]["regular"]
    except Exception as e:
        print(f"⚠️  Unsplash ошибка: {e}")
    return None


def send_message(text: str, image_url: str = None):
    full_text = text + "\n\n<a href='https://t.me/+vJDHO64MwXoxNjIy'>👉 Слышь, новость. Подписаться</a>"

    if image_url:
        requests.post(
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
    print(f"🎬 Пятничный топ | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    genre_ru, genre_en, genre_emoji = get_current_genre()
    print(f"🎭 Жанр этой недели: {genre_ru}")

    movies = fetch_imdb_movies(genre_en)
    print(f"🎥 Найдено фильмов: {len(movies)}")

    if not movies:
        print("❌ Не удалось получить фильмы с IMDb")
        return

    post = make_movies_post(genre_ru, genre_en, genre_emoji, movies)
    if not post:
        print("❌ ИИ не ответил")
        return

    # Ищем фото на Unsplash
    image_url = get_unsplash_photo(f"{genre_en} movie cinema")
    if image_url:
        print("✅ Фото найдено")

    send_message(post, image_url)
    print(f"✅ Пятничный топ опубликован! Жанр: {genre_ru}")


if __name__ == "__main__":
    main()
