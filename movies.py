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

# Жанры TMDB
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
    try:
        response = requests.get(
            "https://api.themoviedb.org/3/discover/movie",
            params={
                "api_key":        TMDB_KEY,
                "with_genres":    genre_id,
                "sort_by":        "vote_average.desc",
                "vote_count.gte": 5000,
                "language":       "ru-RU",
                "include_adult":  False,
                "page":           1,
            },
            timeout=15
        )

        if response.status_code != 200:
            print(f"⚠️  TMDB ответил {response.status_code}")
            return []

        results = response.json().get("results", [])
        movies = []

        for movie in results[:8]:
            title  = movie.get("title", "")
            year   = movie.get("release_date", "")[:4]
            rating = round(movie.get("vote_average", 0), 1)
            poster = movie.get("poster_path", "")

            if title and rating > 0:
                movies.append({
                    "title":  title,
                    "year":   year,
                    "rating": rating,
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
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


def send_message(text: str, movies: list):
    full_text = text + "\n\n<a href='https://t.me/+vJDHO64MwXoxNjIy'>👉 Слышь, новость. Подписаться</a>"

    # Собираем постеры всех 5 фильмов
    posters = [m["poster"] for m in movies if m.get("poster")][:5]

    if len(posters) >= 2:
        # Отправляем медиагруппу — все постеры сразу
        media = [{"type": "photo", "media": url} for url in posters]
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup",
            json={"chat_id": CHAT_ID, "media": media},
            timeout=15
        )
        if resp.status_code == 200:
            print(f"✅ Отправлено {len(posters)} постеров")
        else:
            print(f"⚠️  Медиагруппа не отправилась: {resp.text[:100]}")

        # Текст отдельным сообщением после фото
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
    elif len(posters) == 1:
        # Одно фото с текстом
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            json={
                "chat_id":    CHAT_ID,
                "photo":      posters[0],
                "caption":    full_text,
                "parse_mode": "HTML",
            },
            timeout=15
        )
    else:
        # Без фото
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

    send_message(post, movies)
    print(f"✅ Пятничный топ опубликован! Жанр: {genre_ru}")


if __name__ == "__main__":
    main()
