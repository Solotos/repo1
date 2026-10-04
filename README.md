# 🎬 Meine Filmsammlung

Eine Datenbank für deine DVDs und Blu-rays. Du fotografierst die **Rückseite**
der Hülle, lädst das Foto hoch und die App macht den Rest:

1. **Claude** liest das Cover (Titel, Darsteller, Studio, FSK, Format-Logo …)
   und recherchiert per **Websuche** den Film mit Jahr, Genres, Schauspielern,
   Regie, Laufzeit und Inhaltsangabe.
2. Optional ergänzt **TMDB** (themoviedb.org) das offizielle Filmplakat und
   deutsche Metadaten.
3. Der Film landet mit Cover in der Datenbank (SQLite) und erscheint sofort in
   der Cover-Ansicht.

## Funktionen

- **Foto-Upload** direkt vom Handy (Kamera) oder PC, mehrere Fotos auf einmal,
  per Drag & Drop. Klappt die Erkennung nicht, hilft ein Titel-Hinweis.
- **Cover-Ansicht**: jeder Film mit Plakat und Format-Badge (DVD / Blu-ray / 4K UHD)
- **Einfache Suche** in Titel, Originaltitel, Schauspielern, Regie, Genre und
  Inhalt. Groß-/Kleinschreibung und Akzente sind egal („amelie“ findet „Amélie“).
- **Filtercockpit**:
  - Buchstaben-Leiste A–Z und # (Artikel wie „Der“, „Die“, „The“ werden ignoriert,
    „Der Pate“ steht also unter **P**)
  - Sortierung: Titel A→Z / Z→A, **Datum absteigend**, **Datum aufsteigend**,
    zuletzt / zuerst hinzugefügt
  - **Genre**, **Jahr** und Format (DVD / Blu-ray / 4K)
- **Detailansicht** mit Inhalt, Darstellern, Regie, IMDb-/TMDB-Links. Ein Klick
  auf einen Schauspieler oder ein Genre filtert die Sammlung danach.
- Bearbeiten, Cover austauschen (Upload oder URL), Notizen („verliehen an …“), Löschen
- Doppelte Filme werden erkannt. Dieselbe Edition als DVD *und* Blu-ray ist erlaubt.
- Helles und dunkles Design, funktioniert auf Handy, Tablet und PC

## Installation

Du brauchst Python 3.10 oder neuer.

```bash
git clone <dieses-repo>
cd repo1
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # danach .env öffnen und Schlüssel eintragen
```

### Schlüssel

| Variable | Pflicht? | Woher |
|---|---|---|
| `ANTHROPIC_API_KEY` | **ja** | <https://console.anthropic.com> → API Keys |
| `TMDB_API_KEY` | empfohlen | kostenlos unter <https://www.themoviedb.org/settings/api> (API-Key oder „API Read Access Token“) |

Ohne TMDB-Schlüssel funktioniert alles, aber das Cover stammt dann aus der
Websuche (wenn Claude eines findet) oder es wird dein Foto angezeigt.

## Starten

```bash
python -m filmdb
```

Dann im Browser **http://localhost:5000** öffnen.

**Vom Handy aus:** Handy und PC müssen im selben WLAN sein. Öffne
`http://<IP-deines-PCs>:5000`, z. B. `http://192.168.178.20:5000`. Mit
„＋ Film per Foto“ kannst du dann direkt die Kamera benutzen.

Optionen: `python -m filmdb --port 8080`. Mit `--host 127.0.0.1` ist die App nur
am eigenen PC erreichbar.

## Daten & Backup

Alles liegt im Ordner `data/`:

- `data/filme.sqlite` ist die Datenbank
- `data/covers/` enthält die Filmplakate
- `data/photos/` enthält deine Fotos der Rückseiten

Für ein Backup kopierst du einfach den ganzen `data/`-Ordner. Einen anderen
Speicherort legst du mit der Umgebungsvariable `FILMDB_DATA` fest.

> ⚠️ Die App hat keinen Login. Betreibe sie nur im Heimnetz und gib sie nicht
> ins Internet frei.

## Tipps für gute Erkennung

- Fotografiere die Rückseite gerade, scharf und ohne Spiegelung.
- Ist auf der Rückseite kaum Text, fotografiere die Vorderseite oder gib den
  Titel als Hinweis ein.
- Bei „⚠️ Unsicher erkannt“ öffnest du den Film und korrigierst ihn über
  „Bearbeiten“.
- Jede Erkennung ist ein Aufruf der Claude-API (mit Websuche) und kostet ein
  paar Cent. Das Modell stellst du mit `FILMDB_MODEL` ein (Standard:
  `claude-opus-5-5`).

## Entwicklung

```bash
pip install pytest
python -m pytest
```

Aufbau:

- `filmdb/app.py`: Webserver (Flask) und JSON-API
- `filmdb/db.py`: SQLite, Suche, Filter und Sortierung
- `filmdb/recognizer.py`: Foto → Claude (Bilderkennung + Websuche) → TMDB
- `filmdb/static/`: Oberfläche (HTML/CSS/JS, ohne Build-Schritt)
