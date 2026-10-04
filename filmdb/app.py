"""Web-Oberfläche und JSON-API der Filmsammlung."""
import os
import uuid
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_from_directory

from . import db, recognizer

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def create_app(data_dir=None):
    data_dir = Path(data_dir or os.environ.get("FILMDB_DATA", BASE_DIR.parent / "data"))
    covers_dir = data_dir / "covers"
    photos_dir = data_dir / "photos"
    covers_dir.mkdir(parents=True, exist_ok=True)
    photos_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
    app.config["DB_PATH"] = str(data_dir / "filme.sqlite")

    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    def save_file(folder, content, ext):
        name = f"{uuid.uuid4().hex}{ext}"
        (folder / name).write_bytes(content)
        return name

    def remove_file(folder, name):
        if name and "/" not in name:
            (folder / name).unlink(missing_ok=True)

    # ---------- Seiten & Dateien ----------

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    @app.get("/covers/<path:name>")
    def cover_file(name):
        return send_from_directory(covers_dir, name)

    @app.get("/photos/<path:name>")
    def photo_file(name):
        return send_from_directory(photos_dir, name)

    # ---------- API ----------

    @app.get("/api/movies")
    def list_movies():
        a = request.args
        movies = db.search(
            conn(), q=a.get("q", ""), letter=a.get("letter", ""), genre=a.get("genre", ""),
            year=a.get("year", ""), media_format=a.get("format", ""), sort=a.get("sort", "title"),
        )
        return jsonify(movies=movies, facets=db.facets(conn()))

    @app.get("/api/movies/<int:movie_id>")
    def get_movie(movie_id):
        movie = db.get_movie(conn(), movie_id)
        return jsonify(movie) if movie else abort(404)

    @app.post("/api/movies")
    def create_movie():
        try:
            return jsonify(db.add_movie(conn(), request.get_json(force=True))), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.patch("/api/movies/<int:movie_id>")
    def edit_movie(movie_id):
        if not db.get_movie(conn(), movie_id):
            abort(404)
        data = request.get_json(force=True)
        try:
            movie = db.update_movie(conn(), movie_id, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(movie)

    @app.delete("/api/movies/<int:movie_id>")
    def remove_movie(movie_id):
        movie = db.delete_movie(conn(), movie_id)
        if not movie:
            abort(404)
        remove_file(covers_dir, movie["poster"])
        remove_file(photos_dir, movie["photo"])
        return jsonify(ok=True)

    @app.post("/api/recognize")
    def recognize():
        """Foto (und/oder Titel-Hinweis) hochladen → Film erkennen → speichern."""
        upload = request.files.get("photo")
        hint = request.form.get("hint", "").strip()
        image_bytes = upload.read() if upload else None
        if not image_bytes and not hint:
            return jsonify(error="Bitte ein Foto oder einen Titel angeben"), 400

        try:
            found = recognizer.recognize(image_bytes, hint)
        except recognizer.RecognitionError as exc:
            return jsonify(error=str(exc)), 422

        media_format = request.form.get("format") or found.get("media_format", "")
        duplicate = db.find_duplicate(
            conn(), found.get("title", ""), found.get("year"), media_format, found.get("tmdb_id")
        )
        if duplicate and request.form.get("allow_duplicate") != "1":
            return jsonify(duplicate=True, movie=duplicate, recognized=found), 409

        photo_name = ""
        if image_bytes:
            ext = Path(upload.filename or "").suffix.lower() or ".jpg"
            photo_name = save_file(photos_dir, image_bytes, ext if len(ext) <= 5 else ".jpg")
        cover = recognizer.download_image(found.get("cover_url", ""))
        poster_name = save_file(covers_dir, *cover) if cover else ""

        data = {k: v for k, v in found.items() if k in db.FIELDS}
        data.update(media_format=media_format, poster=poster_name, photo=photo_name)
        try:
            movie = db.add_movie(conn(), data)
        except ValueError as exc:
            remove_file(photos_dir, photo_name)
            remove_file(covers_dir, poster_name)
            return jsonify(error=f"Film nicht erkannt: {exc}"), 422
        return jsonify(movie=movie, confidence=found.get("confidence"), hint=found.get("hinweis")), 201

    @app.post("/api/movies/<int:movie_id>/cover")
    def replace_cover(movie_id):
        """Eigenes Coverbild hochladen oder per URL setzen."""
        movie = db.get_movie(conn(), movie_id) or abort(404)
        upload = request.files.get("cover")
        if upload:
            ext = Path(upload.filename or "").suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                return jsonify(error="Nur JPG, PNG oder WebP"), 400
            cover = (upload.read(), ext)
        else:
            cover = recognizer.download_image((request.form.get("url") or "").strip())
            if not cover:
                return jsonify(error="Bild unter dieser URL nicht ladbar"), 400
        new_name = save_file(covers_dir, *cover)
        remove_file(covers_dir, movie["poster"])
        return jsonify(db.update_movie(conn(), movie_id, {"poster": new_name}))

    return app


def load_env_file(path=BASE_DIR.parent / ".env"):
    """Liest einfache KEY=VALUE-Zeilen aus .env, ohne gesetzte Variablen zu überschreiben."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main():
    import argparse

    load_env_file()
    parser = argparse.ArgumentParser(description="Filmsammlung starten")
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = auch vom Handy im WLAN erreichbar")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
