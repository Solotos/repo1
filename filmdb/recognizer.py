"""Erkennt einen Film anhand eines Fotos der DVD-/Blu-ray-Rückseite.

1. Claude liest das Cover (Bilderkennung) und recherchiert per Websuche die Metadaten.
2. Ist ein TMDB-API-Schlüssel gesetzt, werden Poster, Genres, Besetzung und
   Inhaltsangabe zusätzlich von themoviedb.org (deutsch) ergänzt.
"""
import base64
import io
import logging
import os

import anthropic
import requests

log = logging.getLogger(__name__)

MODEL = os.environ.get("FILMDB_MODEL", "claude-opus-5-5")
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
MAX_IMAGE_SIDE = 1568

SYSTEM_PROMPT = """Du katalogisierst eine private DVD- und Blu-ray-Sammlung.
Du bekommst ein Foto der Rückseite (manchmal auch der Vorderseite) einer Filmhülle.

Vorgehen:
1. Lies alles, was auf dem Cover steht: Titel, Darsteller, Regie, Studio/Label,
   FSK-Logo, Laufzeit, Erscheinungsjahr/Copyright, Barcode, Format-Logos
   (DVD, Blu-ray, 4K Ultra HD).
2. Recherchiere mit der Websuche, um welchen Film es sich genau handelt, und
   ergänze verlässliche Metadaten: deutscher Titel, Originaltitel,
   Erscheinungsjahr des Films (Kinostart, nicht das Jahr der Disc-Auflage),
   Genres (auf Deutsch), Hauptdarsteller, Regie, Laufzeit, kurze deutsche
   Inhaltsangabe, IMDb-ID und TMDB-ID, falls auffindbar.
3. cover_url: eine direkte Bild-URL (.jpg/.png/.webp) des Filmplakats oder
   Frontcovers, wenn du in den Suchergebnissen eine findest, sonst "".
4. Rufe zum Schluss genau einmal das Werkzeug film_speichern auf.

Unbekannte Textfelder sind "", unbekannte Zahlen 0, unbekannte Listen [].
Erfinde nichts: Wenn du den Film nicht sicher bestimmen kannst, setze
confidence auf "niedrig" und erkläre in hinweis, was fehlt."""

SAVE_TOOL = {
    "name": "film_speichern",
    "description": "Speichert die erkannten Metadaten eines Films in der Sammlung.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Deutscher Titel, wie er auf der Hülle steht"},
            "original_title": {"type": "string"},
            "year": {"type": "integer", "description": "Erscheinungsjahr des Films"},
            "release_date": {"type": "string", "description": "Kinostart als JJJJ-MM-TT, falls bekannt"},
            "genres": {"type": "array", "items": {"type": "string"}},
            "actors": {"type": "array", "items": {"type": "string"}, "description": "Hauptdarsteller, max. 10"},
            "directors": {"type": "array", "items": {"type": "string"}},
            "runtime": {"type": "integer", "description": "Laufzeit in Minuten"},
            "overview": {"type": "string", "description": "Kurze deutsche Inhaltsangabe"},
            "media_format": {"type": "string", "enum": ["DVD", "Blu-ray", "4K UHD", ""]},
            "studio": {"type": "string"},
            "fsk": {"type": "string", "description": "z. B. 'FSK 12'"},
            "imdb_id": {"type": "string", "description": "z. B. tt0133093"},
            "tmdb_id": {"type": "integer"},
            "cover_url": {"type": "string"},
            "confidence": {"type": "string", "enum": ["hoch", "mittel", "niedrig"]},
            "hinweis": {"type": "string", "description": "Anmerkungen zur Erkennung"},
        },
        "required": [
            "title", "original_title", "year", "release_date", "genres", "actors",
            "directors", "runtime", "overview", "media_format", "studio", "fsk",
            "imdb_id", "tmdb_id", "cover_url", "confidence", "hinweis",
        ],
        "additionalProperties": False,
    },
}

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}


class RecognitionError(Exception):
    pass


def prepare_image(raw_bytes):
    """Verkleinert große Handyfotos und liefert (media_type, base64)."""
    try:
        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_bytes)))
        img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()
    except Exception as exc:  # Pillow fehlt oder Format unbekannt
        raise RecognitionError(f"Bild konnte nicht gelesen werden: {exc}") from exc


def ask_claude(image_bytes=None, hint=""):
    if not image_bytes and not hint:
        raise RecognitionError("Weder Foto noch Titel angegeben")

    content = []
    if image_bytes:
        media_type, data = prepare_image(image_bytes)
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
        text = "Welcher Film ist das? Recherchiere die Metadaten und speichere ihn."
    else:
        text = "Recherchiere die Metadaten zu diesem Film und speichere ihn."
    if hint:
        text += f"\nHinweis des Sammlers: {hint}"
    content.append({"type": "text", "text": text})
    messages = [{"role": "user", "content": content}]

    client = anthropic.Anthropic()
    nudged = False
    for _ in range(8):
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=[WEB_SEARCH_TOOL, SAVE_TOOL],
                tool_choice={"type": "auto"},
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=messages,
            )
        except anthropic.AuthenticationError as exc:
            raise RecognitionError("ANTHROPIC_API_KEY fehlt oder ist ungültig") from exc
        except anthropic.RateLimitError as exc:
            raise RecognitionError("Zu viele Anfragen an Claude – bitte kurz warten") from exc
        except anthropic.APIStatusError as exc:
            raise RecognitionError(f"Claude-API-Fehler ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RecognitionError("Keine Verbindung zur Claude-API") from exc

        if response.stop_reason == "refusal":
            raise RecognitionError("Claude hat die Anfrage abgelehnt")

        for block in response.content:
            if block.type == "tool_use" and block.name == SAVE_TOOL["name"]:
                return dict(block.input)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue  # Websuche läuft noch – einfach fortsetzen
        if nudged:
            break
        nudged = True
        messages.append({"role": "user", "content": "Bitte rufe jetzt film_speichern mit deinem Ergebnis auf."})

    raise RecognitionError("Der Film konnte nicht erkannt werden")


def _tmdb_get(path, **params):
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        return None
    headers = {"accept": "application/json"}
    # Neuer "API Read Access Token" (JWT) oder klassischer v3-API-Key
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    params.setdefault("language", "de-DE")
    try:
        resp = requests.get(f"{TMDB_API}{path}", params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.warning("TMDB-Anfrage %s fehlgeschlagen: %s", path, exc)
        return None


def _find_tmdb_id(movie):
    if movie.get("tmdb_id"):
        return movie["tmdb_id"]
    if movie.get("imdb_id"):
        found = _tmdb_get(f"/find/{movie['imdb_id']}", external_source="imdb_id")
        if found and found.get("movie_results"):
            return found["movie_results"][0]["id"]
    for query in filter(None, (movie.get("original_title"), movie.get("title"))):
        params = {"query": query}
        if movie.get("year"):
            params["year"] = movie["year"]
        found = _tmdb_get("/search/movie", **params)
        if found and found.get("results"):
            return found["results"][0]["id"]
    return None


def enrich_with_tmdb(movie):
    """Ergänzt Poster und Metadaten von TMDB (nur mit TMDB_API_KEY)."""
    if not os.environ.get("TMDB_API_KEY"):
        return movie
    tmdb_id = _find_tmdb_id(movie)
    details = tmdb_id and _tmdb_get(f"/movie/{tmdb_id}", append_to_response="credits")
    if not details:
        return movie

    merged = dict(movie)
    merged["tmdb_id"] = details["id"]
    if details.get("poster_path"):
        merged["cover_url"] = TMDB_IMG + details["poster_path"]
    if details.get("genres"):
        merged["genres"] = [g["name"] for g in details["genres"]]
    if details.get("overview"):
        merged["overview"] = details["overview"]
    if details.get("release_date"):
        merged["release_date"] = details["release_date"]
        merged["year"] = int(details["release_date"][:4])
    if details.get("runtime"):
        merged["runtime"] = details["runtime"]
    if details.get("imdb_id"):
        merged["imdb_id"] = details["imdb_id"]
    if details.get("original_title"):
        merged["original_title"] = details["original_title"]
    if details.get("vote_average"):
        merged["rating"] = round(details["vote_average"], 1)
    credits = details.get("credits") or {}
    cast = [c["name"] for c in credits.get("cast", [])[:10]]
    if cast:
        merged["actors"] = cast
    directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
    if directors:
        merged["directors"] = directors
    return merged


def download_image(url):
    """Lädt ein Coverbild herunter; liefert (bytes, endung) oder None."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 FilmDB"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.info("Cover %s nicht ladbar: %s", url, exc)
        return None
    ctype = resp.headers.get("content-type", "").split(";")[0].strip()
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(ctype)
    if not ext or len(resp.content) < 2000:
        return None
    return resp.content, ext


def recognize(image_bytes=None, hint=""):
    movie = ask_claude(image_bytes, hint)
    movie = enrich_with_tmdb(movie)
    return movie
