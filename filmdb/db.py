"""SQLite-Speicher für die Filmsammlung."""
import json
import sqlite3
import unicodedata
from datetime import datetime, timezone

LIST_FIELDS = ("genres", "actors", "directors")

FIELDS = (
    "title", "original_title", "year", "release_date", "genres", "actors",
    "directors", "runtime", "overview", "media_format", "studio", "fsk",
    "rating", "tmdb_id", "imdb_id", "poster", "photo", "notes",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    original_title TEXT DEFAULT '',
    year INTEGER,
    release_date TEXT DEFAULT '',
    genres TEXT DEFAULT '[]',
    actors TEXT DEFAULT '[]',
    directors TEXT DEFAULT '[]',
    runtime INTEGER,
    overview TEXT DEFAULT '',
    media_format TEXT DEFAULT '',
    studio TEXT DEFAULT '',
    fsk TEXT DEFAULT '',
    rating REAL,
    tmdb_id INTEGER,
    imdb_id TEXT DEFAULT '',
    poster TEXT DEFAULT '',
    photo TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""

# Artikel, die beim Sortieren und bei der Buchstaben-Filterung ignoriert werden
# ("Der Pate" steht unter P, "The Matrix" unter M).
ARTICLES = ("der ", "die ", "das ", "the ", "a ", "an ", "ein ", "eine ", "le ", "la ", "les ")


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _row_to_dict(row):
    movie = dict(row)
    for key in LIST_FIELDS:
        movie[key] = json.loads(movie[key] or "[]")
    movie["sort_title"] = sort_title(movie["title"])
    movie["letter"] = letter_of(movie["title"])
    return movie


def _clean(data):
    values = {}
    for key in FIELDS:
        if key not in data:
            continue
        value = data[key]
        if key in LIST_FIELDS:
            value = json.dumps([str(v).strip() for v in (value or []) if str(v).strip()], ensure_ascii=False)
        elif key in ("year", "runtime", "tmdb_id"):
            value = int(value) if value not in (None, "", 0, "0") else None
        elif key == "rating":
            value = float(value) if value not in (None, "") else None
        else:
            value = (value or "").strip() if isinstance(value, str) else (value or "")
        values[key] = value
    return values


def fold(text):
    """Kleinschreibung ohne Akzente, damit 'amelie' auch 'Amélie' findet."""
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def sort_title(title):
    folded = fold(title).strip()
    for article in ARTICLES:
        if folded.startswith(article) and len(folded) > len(article):
            return folded[len(article):].lstrip()
    return folded


def letter_of(title):
    first = sort_title(title)[:1].upper()
    return first if "A" <= first <= "Z" else "#"


def add_movie(conn, data):
    values = _clean(data)
    if not values.get("title"):
        raise ValueError("Titel fehlt")
    values["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO movies ({cols}) VALUES ({marks})", tuple(values.values()))
    conn.commit()
    return get_movie(conn, cur.lastrowid)


def update_movie(conn, movie_id, data):
    values = _clean(data)
    if "title" in values and not values["title"]:
        raise ValueError("Titel fehlt")
    if values:
        assignments = ", ".join(f"{key} = ?" for key in values)
        conn.execute(f"UPDATE movies SET {assignments} WHERE id = ?", (*values.values(), movie_id))
        conn.commit()
    return get_movie(conn, movie_id)


def delete_movie(conn, movie_id):
    movie = get_movie(conn, movie_id)
    conn.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
    conn.commit()
    return movie


def get_movie(conn, movie_id):
    row = conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
    return _row_to_dict(row) if row else None


def all_movies(conn):
    return [_row_to_dict(r) for r in conn.execute("SELECT * FROM movies")]


def find_duplicate(conn, title, year, media_format, tmdb_id=None):
    for movie in all_movies(conn):
        if (movie["media_format"] or "") != (media_format or ""):
            continue
        if tmdb_id and movie["tmdb_id"] == tmdb_id:
            return movie
        if fold(movie["title"]) == fold(title) and (movie["year"] or None) == (year or None):
            return movie
    return None


SORTS = {
    "title": (lambda m: m["sort_title"], False),
    "title_desc": (lambda m: m["sort_title"], True),
    "year_desc": (lambda m: (m["release_date"] or str(m["year"] or 0), m["sort_title"]), True),
    "year_asc": (lambda m: (m["release_date"] or str(m["year"] or 9999), m["sort_title"]), False),
    "added_desc": (lambda m: (m["created_at"], m["id"]), True),
    "added_asc": (lambda m: (m["created_at"], m["id"]), False),
}


def search(conn, q="", letter="", genre="", year="", media_format="", sort="title"):
    """Filtert in Python statt SQL, damit Umlaute/Akzente sauber verglichen werden."""
    movies = all_movies(conn)
    if q:
        terms = fold(q).split()

        def haystack(m):
            parts = [m["title"], m["original_title"], m["overview"], m["studio"], str(m["year"] or "")]
            parts += m["actors"] + m["directors"] + m["genres"]
            return fold(" ".join(parts))

        movies = [m for m in movies if all(t in haystack(m) for t in terms)]
    if letter:
        movies = [m for m in movies if m["letter"] == letter.upper()]
    if genre:
        movies = [m for m in movies if genre in m["genres"]]
    if year:
        movies = [m for m in movies if str(m["year"] or "") == str(year)]
    if media_format:
        movies = [m for m in movies if m["media_format"] == media_format]
    key, reverse = SORTS.get(sort, SORTS["title"])
    # Filme ohne Jahr landen bei der Jahressortierung immer am Ende.
    if sort in ("year_desc", "year_asc"):
        with_year = sorted((m for m in movies if m["year"]), key=key, reverse=reverse)
        return with_year + sorted((m for m in movies if not m["year"]), key=SORTS["title"][0])
    return sorted(movies, key=key, reverse=reverse)


def facets(conn):
    movies = all_movies(conn)
    genres = sorted({g for m in movies for g in m["genres"]}, key=fold)
    years = sorted({m["year"] for m in movies if m["year"]}, reverse=True)
    letters = sorted({m["letter"] for m in movies})
    formats = sorted({m["media_format"] for m in movies if m["media_format"]})
    return {"genres": genres, "years": years, "letters": letters, "formats": formats, "total": len(movies)}
