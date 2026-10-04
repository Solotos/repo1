import io

import pytest

from filmdb import app as app_module
from filmdb import db, recognizer

MATRIX = {
    "title": "Matrix", "original_title": "The Matrix", "year": 1999, "release_date": "1999-06-17",
    "genres": ["Action", "Science Fiction"], "actors": ["Keanu Reeves", "Carrie-Anne Moss"],
    "directors": ["Lana Wachowski"], "runtime": 136, "overview": "Neo erfährt die Wahrheit.",
    "media_format": "Blu-ray", "studio": "Warner", "fsk": "FSK 16", "imdb_id": "tt0133093",
    "tmdb_id": 603, "cover_url": "", "confidence": "hoch", "hinweis": "",
}


@pytest.fixture
def client(tmp_path):
    return app_module.create_app(tmp_path).test_client()


def add(client, **data):
    resp = client.post("/api/movies", json=data)
    assert resp.status_code == 201, resp.json
    return resp.json


def test_sort_title_ignores_articles():
    assert db.sort_title("Der Pate") == "pate"
    assert db.letter_of("The Matrix") == "M"
    assert db.letter_of("Die Ärzte") == "A"
    assert db.letter_of("2001: Odyssee im Weltraum") == "#"


def test_search_and_filters(client):
    add(client, title="Der Pate", year=1972, genres=["Drama", "Krimi"], actors=["Marlon Brando"], media_format="DVD")
    add(client, title="Amélie", year=2001, genres=["Komödie"], media_format="Blu-ray")
    add(client, title="Inception", year=2010, genres=["Action", "Science Fiction"], actors=["Leonardo DiCaprio"], media_format="Blu-ray")

    def titles(**params):
        return [m["title"] for m in client.get("/api/movies", query_string=params).json["movies"]]

    assert titles() == ["Amélie", "Inception", "Der Pate"]
    assert titles(q="amelie") == ["Amélie"]
    assert titles(q="dicaprio") == ["Inception"]
    assert titles(letter="P") == ["Der Pate"]
    assert titles(genre="Action") == ["Inception"]
    assert titles(year=1972) == ["Der Pate"]
    assert titles(format="Blu-ray") == ["Amélie", "Inception"]
    assert titles(sort="year_desc") == ["Inception", "Amélie", "Der Pate"]
    assert titles(sort="year_asc") == ["Der Pate", "Amélie", "Inception"]

    facets = client.get("/api/movies").json["facets"]
    assert facets["years"] == [2010, 2001, 1972]
    assert facets["letters"] == ["A", "I", "P"]
    assert "Komödie" in facets["genres"]


def test_edit_and_delete(client):
    movie = add(client, title="Alien", year=1979)
    resp = client.patch(f"/api/movies/{movie['id']}", json={"genres": ["Horror"], "notes": "verliehen"})
    assert resp.json["genres"] == ["Horror"]
    assert resp.json["notes"] == "verliehen"
    assert client.patch(f"/api/movies/{movie['id']}", json={"title": ""}).status_code == 400
    assert client.delete(f"/api/movies/{movie['id']}").status_code == 200
    assert client.get(f"/api/movies/{movie['id']}").status_code == 404


def test_recognize_photo(client, monkeypatch):
    calls = []

    def fake_recognize(image_bytes, hint):
        calls.append((image_bytes, hint))
        return dict(MATRIX)

    monkeypatch.setattr(recognizer, "recognize", fake_recognize)
    monkeypatch.setattr(recognizer, "download_image", lambda url: None)

    photo = (io.BytesIO(b"fake-jpeg"), "rueckseite.jpg")
    resp = client.post("/api/recognize", data={"photo": photo}, content_type="multipart/form-data")
    assert resp.status_code == 201, resp.json
    movie = resp.json["movie"]
    assert movie["title"] == "Matrix"
    assert movie["media_format"] == "Blu-ray"
    assert movie["actors"][0] == "Keanu Reeves"
    assert movie["photo"].endswith(".jpg")
    assert client.get(f"/photos/{movie['photo']}").data == b"fake-jpeg"
    assert calls == [(b"fake-jpeg", "")]

    # Gleicher Film nochmal → Duplikat-Hinweis, mit allow_duplicate trotzdem speichern
    photo = (io.BytesIO(b"fake-jpeg"), "rueckseite.jpg")
    resp = client.post("/api/recognize", data={"photo": photo}, content_type="multipart/form-data")
    assert resp.status_code == 409
    resp = client.post("/api/recognize", data={"hint": "Matrix", "allow_duplicate": "1"})
    assert resp.status_code == 201

    # Gleicher Film als DVD ist kein Duplikat
    resp = client.post("/api/recognize", data={"hint": "Matrix", "format": "DVD"})
    assert resp.status_code == 201
    assert resp.json["movie"]["media_format"] == "DVD"


def test_recognize_error(client, monkeypatch):
    def fail(image_bytes, hint):
        raise recognizer.RecognitionError("ANTHROPIC_API_KEY fehlt oder ist ungültig")

    monkeypatch.setattr(recognizer, "recognize", fail)
    resp = client.post("/api/recognize", data={"hint": "Matrix"})
    assert resp.status_code == 422
    assert "API_KEY" in resp.json["error"]
    assert client.post("/api/recognize", data={}).status_code == 400


def test_tmdb_enrichment(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "abc")
    details = {
        "id": 603, "poster_path": "/p.jpg", "genres": [{"name": "Action"}], "overview": "Text",
        "release_date": "1999-03-30", "runtime": 136, "imdb_id": "tt0133093",
        "original_title": "The Matrix", "vote_average": 8.21,
        "credits": {"cast": [{"name": "Keanu Reeves"}], "crew": [{"name": "Lilly Wachowski", "job": "Director"}]},
    }
    monkeypatch.setattr(recognizer, "_tmdb_get", lambda path, **p: details if path == "/movie/603" else None)
    merged = recognizer.enrich_with_tmdb(dict(MATRIX))
    assert merged["cover_url"] == recognizer.TMDB_IMG + "/p.jpg"
    assert merged["rating"] == 8.2
    assert merged["directors"] == ["Lilly Wachowski"]
    assert merged["year"] == 1999


def test_prepare_image_shrinks_large_photo():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(buf, format="PNG")
    media_type, data = recognizer.prepare_image(buf.getvalue())
    assert media_type == "image/jpeg"
    assert data
