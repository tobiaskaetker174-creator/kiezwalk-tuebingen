"""Prüfregeln für city-bundles/tuebingen.json.

Dieselbe Prüfung läuft serverseitig (VPS-Wächter, eigene Kopie) vor jeder
Veröffentlichung. Was hier scheitert, geht nie live.
"""
import json
import re

MAX_BYTES = 24 * 1024 * 1024
MEDIA_BASE = "https://tobiaskaetker174-creator.github.io/kiezwalk-tuebingen/media/"
_AUDIO = re.compile(r"^" + re.escape(MEDIA_BASE) + r"audio/[a-z0-9][a-z0-9._-]*\.(mp3|m4a|wav|ogg)$")
_IMAGE = re.compile(r"^" + re.escape(MEDIA_BASE) + r"images/[a-z0-9][a-z0-9._-]*\.(webp|jpg|jpeg|png)$")
_DATA_IMAGE = re.compile(r"^data:image/(webp|png|jpeg);base64,[A-Za-z0-9+/=]+$")
_ID = re.compile(r"^tuebingen-[a-z0-9-]+$")
TOP_KEYS = {"schema", "city_id", "status", "packages", "images", "map"}
# großzügige Box um Tübingen inkl. Umland
LAT, LNG = (48.35, 48.70), (8.85, 9.25)


def validate(raw: bytes, previous_card_count: int | None = None) -> list[str]:
    """Liefert eine Liste von Fehlern; leer = gültig."""
    errors = []
    if len(raw) > MAX_BYTES:
        return [f"Datei zu groß: {len(raw)} Bytes (max {MAX_BYTES})"]
    try:
        d = json.loads(raw)
    except Exception as e:
        return [f"Kein gültiges JSON: {e}"]
    if not isinstance(d, dict):
        return ["Bundle ist kein JSON-Objekt"]
    if d.get("schema") != "kiezwalk.city-bundle.v1":
        errors.append("schema muss 'kiezwalk.city-bundle.v1' sein")
    if d.get("city_id") != "tuebingen":
        errors.append("city_id muss 'tuebingen' sein")
    extra = set(d) - TOP_KEYS
    if extra:
        errors.append(f"Unbekannte Felder oben: {sorted(extra)}")
    images = d.get("images") or {}
    if not isinstance(images, dict):
        errors.append("images muss ein Objekt sein")
        images = {}
    for k, v in images.items():
        if not re.fullmatch(r"[a-f0-9]{64}", k) or not isinstance(v, str) or not _DATA_IMAGE.match(v):
            errors.append(f"Ungültiges eingebettetes Bild {k[:16]}")
    pkgs = d.get("packages")
    if not isinstance(pkgs, dict) or not pkgs:
        return errors + ["packages fehlt oder leer"]
    total, seen = 0, set()
    for pid, p in pkgs.items():
        if not _ID.match(pid):
            errors.append(f"Paket-ID nicht Tübingen: {pid}")
            continue
        m = (p or {}).get("manifest") or {}
        if m.get("package_id") != pid or m.get("city_id") != "tuebingen":
            errors.append(f"{pid}: manifest.package_id/city_id passt nicht")
        cards = p.get("factCards")
        if not isinstance(cards, list):
            errors.append(f"{pid}: factCards fehlt")
            continue
        for c in cards:
            cid = c.get("id", "?")
            where = f"{pid}/{cid}"
            if not _ID.match(str(cid)):
                errors.append(f"{where}: Karten-ID muss mit 'tuebingen-' beginnen (nur a-z, 0-9, -)")
            if (pid, cid) in seen:
                errors.append(f"{where}: doppelte Karten-ID")
            seen.add((pid, cid))
            if c.get("city_id") != "tuebingen":
                errors.append(f"{where}: city_id muss 'tuebingen' sein")
            if not str(c.get("title") or "").strip():
                errors.append(f"{where}: Titel fehlt")
            if not str(c.get("short_description") or "").strip():
                errors.append(f"{where}: short_description fehlt")
            lat, lng = c.get("lat"), c.get("lng")
            if not (isinstance(lat, (int, float)) and isinstance(lng, (int, float))
                    and LAT[0] <= lat <= LAT[1] and LNG[0] <= lng <= LNG[1]):
                errors.append(f"{where}: lat/lng fehlt oder liegt nicht in Tübingen")
            for key, a in (c.get("audio_assets") or {}).items():
                url = (a or {}).get("url") or ""
                if url and not _AUDIO.match(url):
                    errors.append(f"{where}: Audio-URL {key} nicht erlaubt: {url[:90]}")
            for img in c.get("images") or []:
                url = (img or {}).get("url") or ""
                if url.startswith("bundle-image:"):
                    if url[13:] not in images:
                        errors.append(f"{where}: eingebettetes Bild fehlt {url[13:29]}")
                elif not _IMAGE.match(url):
                    errors.append(f"{where}: Bild-URL nicht erlaubt: {url[:90]}")
                elif not (img.get("license") and img.get("credit") and img.get("source_url")):
                    errors.append(f"{where}: Bild ohne license/credit/source_url")
            total += 1
    if previous_card_count and total < previous_card_count * 0.8:
        errors.append(f"Zu viele Karten weg: {total} statt bisher {previous_card_count} (Schutz gegen Versehen)")
    return errors


def card_count(raw: bytes) -> int:
    d = json.loads(raw)
    return sum(len(p.get("factCards") or []) for p in d.get("packages", {}).values())
