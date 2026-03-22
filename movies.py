# movies.py — Пятничный топ фильмов
# Каждую пятницу в 18:00 по Киеву публикует топ-5 фильмов по жанру
# Жанр меняется каждую неделю чтобы не повторяться

import requests
import os
from datetime import datetime, timezone, timedelta

BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = os.environ["CHAT_ID"]
GROQ_KEY     = os.environ["GROQ_KEY"]
TMDB_KEY     = os.environ["TMDB_KEY"]
UNSPLASH_KEY = os.environ.get("UNSPLASH_KEY", "")

# Жанры TMDB — ID жанров из их API
GENRES = [
    ("комедии",        35,   "😂"),
    ("триллеры",       53,   "😱"),
    ("драмы",          18,   "🎭"),
    ("фантастика",     878,  "🚀"),
    ("боевики",        28,   "💥"),
    ("криминал",       80,   "🔍"),
    ("анимация",       16,   "🎨"),
    ("документальные", 99,   "🎬"),
    ("ужасы",          27,   "👻"),
    ("приключения",    12,   "🗺"),
]

MOVIES_PROMPT = """Ты — редактор Telegram-канала «Слышь, новость».
Напиши пятничный пост про топ-5 фильмов жанра «{genre_ru}».

Список фильмов:
{movies_list}

Напиши пост строго в таком формате:

🎬 <b>Пятничный топ: {genre_emoji} {genre_ru} на вечер</b>

[одна фраза-затравка почему стоит смотреть этот жанр сегодня]

1️⃣ <b>[название фильма 1]</b> ([год]) — ⭐ [рейтинг]
[одно предложение почему стоит посмотреть, без спойлеров]

2️⃣ <b>[название фильма 2]</b> ([год]) — ⭐ [рейтинг]
[одно предложение почему стоит посмотреть, без спойлеров]

3️⃣ <b>[название фильма 3]</b> ([год]) — ⭐ [рейтинг]
[одно предложение почему стоит посмотреть, без спойлеров]

4️⃣ <b>[название фильма 4]</b> ([год]) — ⭐ [рейтинг]
[одно предложение почему стоит посмотреть, без спойлеров]

5️⃣ <b>[название фильма 5]</b> ([год]) — ⭐ [рейтинг]
[одно предложение почему стоит посмотреть, без спойлеров]

[короткая итоговая фраза — пожелание хорошего вечера]

Пиши на русском языке, живо и с характером."""


def get_current_genre():
    week_number = datetime.now(timezone.utc).isocalendar()[1]
    return GENRES[week_number % len(GENRES)]


def fetch_tmdb_movies(genre_id: int) -> list:
    """Получает топ фильмов с TMDB по жанру."""
    try:
        response = requests.get(
            "https://api.themoviedb.org/3/discover/movie",
            params={
                "api_key":              TMDB_KEY,
                "with_genres":          genre_id,
                "sort_by":              "vote_average.desc",
                "vote_count.gte":       5000,
                "language":             "ru-RU",
                "include_adult":        False,
                "page":                 1,
            },
            timeout=15
        )

        if response.status_code != 200:
            print(f"⚠️  TMDB ответил {response.status_code}: {response.text[:200]}")
            return []

        results = response.json().get("results", [])
        movies = []

        for movie in results[:8]:
            title   = movie.get("title", "")
            year    = movie.get("release_date", "")[:4]
            rating  = round(movie.get("vote_average", 0), 1)
            poster  = movie.get("poster_path", "")

            if title and rating > 0:
                movies.append({
                    "title":  title,
                    "year":   year,
                    "rating": rating,
                    "poster": f"https://image.tmdb.org/t/p/w780{poster}" if poster else None
                })

        return movies[:5]

    except Exception as e:
        print(f"⚠️  Ошибка TMDB: {e}")
        return []


def make_movies_post(genre_ru: str, genre_emoji: str, movies: list) -> str:
    if not movies:
        return None

    movies_list = "\n".join(
        f"{i+1}. {m['title']} ({m['year']}) — ⭐ {m['rating']}"
        for i, m in enumerate(movies)
    )

    prompt = MOVIES_PROMPT.format(
        genre_ru=genre_ru,
        genre_emoji=genre_emoji,
        movies_list=movies_list,
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
                "max_tokens": 800,
                "temperature": 0.8
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        print(f"⚠️  Groq ошибка: {response.status_code}")
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
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            json={
                "chat_id":    CHAT_ID,
                "photo":      image_url,
                "caption":    full_text,
                "parse_mode": "HTML",
            },
            timeout=15
        )
        if resp.status_code != 200:
            print(f"⚠️  Фото не загрузилось, публикую без фото")
            send_message(text, image_url=None)
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

    genre_ru, genre_id, genre_emoji = get_current_genre()
    print(f"🎭 Жанр этой недели: {genre_ru} (ID: {genre_id})")

    movies = fetch_tmdb_movies(genre_id)
    print(f"🎥 Найдено фильмов: {len(movies)}")

    if not movies:
        print("❌ Не удалось получить фильмы с TMDB")
        return

    for m in movies:
        print(f"   • {m['title']} ({m['year']}) ⭐{m['rating']}")

    post = make_movies_post(genre_ru, genre_emoji, movies)
    if not post:
        print("❌ ИИ не ответил")
        return

    # Фото: постер первого фильма или Unsplash
    image_url = movies[0].get("poster") if movies else None
    if not image_url:
        image_url = get_unsplash_photo(f"{genre_ru} cinema movie")
        if image_url:
            print("✅ Фото с Unsplash")
    else:
        print("✅ Постер фильма с TMDB")

    send_message(post, image_url)
    print(f"✅ Пятничный топ опубликован! Жанр: {genre_ru}")


if __name__ == "__main__":
    main()
