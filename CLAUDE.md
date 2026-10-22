# KiezWalk Tübingen – Arbeitsregeln für Agenten

Dieses Repo ist die Quelle für https://kiezwalk.com/tuebingen. Was hier auf `main` liegt und die Prüfung besteht, stellt ein Server automatisch live (alle 5 Minuten, Dauer meist 5–15 Minuten). Du darfst und sollst Tübingen selbstständig bearbeiten und veröffentlichen – ohne Rückfrage bei Tobias.

## Was es gibt
- `city-bundles/tuebingen.json` – alle Tübinger Karten (Pakete `tuebingen-stadtgebiet-de/-en` = Hauptkarte, `tuebingen-weekend-de/-en` = Tourist-Auswahl).
- `media/audio/`, `media/images/` – Audio/Bilder. Werden über https://tobiaskaetker174-creator.github.io/kiezwalk-tuebingen/media/… ausgeliefert. Dateinamen enthalten einen Hash, nie überschreiben.
- `tools/kiezwalk.py` – alles Nötige: `list`, `show`, `new-card`, `tts`, `add-image`, `validate`, `publish`, `status`. Hilfe: `python tools/kiezwalk.py <befehl> --help`.
- `texte/` – Arbeitsentwürfe, Recherche-Notizen.

## Ablauf für eine Karte
1. Recherche: echte Quellen öffnen und lesen (Stadt Tübingen, Uni, Stadtmuseum, Schwäbisches Tagblatt, Landesarchiv, Wikipedia nur als Einstieg). Nichts erfinden.
2. Texte schreiben (DE und EN, gleiche Fakten): Short 60–120 Wörter, Deep Dive 180–260 Wörter mit Neuem statt Wiederholung.
3. `new-card` je Sprache (gleicher `--slug`), Quellen als JSON-Datei mitgeben.
4. Bild: Wikimedia Commons (freie Lizenz), herunterladen, auf max. 1600 px / 1,5 MB, `add-image` mit Caption, Credit, Lizenz, Lizenz-URL, Quell-URL. KI-Bilder nur mit `--generated`.
5. Audio: `tts <id-de> --part short`, `--part deep`, dasselbe für `-en`. Danach mindestens eine Aufnahme anhören (Aussprache von Namen!).
6. `validate`, dann `publish -m "…"` – wartet, bis es live ist.
7. Auf https://kiezwalk.com/tuebingen im Browser prüfen.

## Textstil
Ort und Thema in den ersten 1–2 Sätzen. Erwachsen, natürlich, beim Gehen verständlich. Keine Rätsel, Faktenlisten oder Werbesprache. Lebendige lokale Geschichten vor Namensgebern; gern auch Jüngeres (letzte 10 Jahre), Konflikte, Kurioses. Jede Tatsache belegt. Reale Personen/Straftaten nie erfinden. Kein Meta-Text in der App („Demo“, „KI“, „Entwurf“).

## Grenzen (technisch erzwungen)
- Nur Tübingen. Karten-IDs `tuebingen-<slug>-de|en`, Koordinaten im Raum Tübingen.
- Medien nur aus `media/` dieses Repos; keine fremden URLs.
- Mehr als 20 % der Karten auf einmal löschen wird abgelehnt.
- Bestehende Karten dürfen geändert und verbessert werden; IDs bleiben gleich.
- Kosten: TTS läuft im Gemini-Gratis-Kontingent. Nie Abrechnung aktivieren, nie neue Schlüssel/Projekte anlegen. Bei 429 pausieren.
- Schlüssel nie in Dateien, Commits, Chat oder Logs.

## Status prüfen
`python tools/kiezwalk.py status` oder auf GitHub beim Commit der Status „kiezwalk/live“. Bei „failure“ steht der Grund in der Beschreibung – beheben und neu `publish`.
