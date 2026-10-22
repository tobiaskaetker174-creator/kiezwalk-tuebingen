"""KiezWalk Tübingen – Werkzeug für Inhalte, Audio, Bilder und Veröffentlichung.

Nur Python-Standardbibliothek. Läuft im Repo-Ordner (kiezwalk-tuebingen).

  python tools/kiezwalk.py setup-key            Gemini-Schlüssel sicher in Windows ablegen
  python tools/kiezwalk.py list [--lang de]     Karten auflisten
  python tools/kiezwalk.py show <karten-id>     Eine Karte anzeigen
  python tools/kiezwalk.py new-card ...         Neue Karte anlegen (siehe --help)
  python tools/kiezwalk.py tts <karten-id> [--part short|deep]
  python tools/kiezwalk.py add-image <karten-id> <bilddatei> --caption ... --credit ... --license ... --license-url ... --source-url ...
  python tools/kiezwalk.py validate             Prüfen wie der Server
  python tools/kiezwalk.py publish -m "Text"    Commit + Push; Server stellt live (ca. 5–15 min)
  python tools/kiezwalk.py status               Ist der aktuelle Stand live?
"""
import argparse
import base64
import copy
import ctypes
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_bundle import MEDIA_BASE, card_count, validate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "city-bundles" / "tuebingen.json"
REPO = "tobiaskaetker174-creator/kiezwalk-tuebingen"
LIVE_URL = "https://kiezwalk.com/city-bundles/tuebingen.json"
CRED_TARGET = "kiezwalk-gemini-tts"
TTS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
TTS_MODEL = "gemini-3.8-flash-tts"
VOICE = "Algieba"
STYLE = {
    "de": "ruhig, erwachsen und natürlich erzählend, wie eine Stadtführerin beim Gehen; deutliche Aussprache, kein Werbeton",
    "en": "calm, adult, natural storytelling like a local guide on a walk; clear pronunciation, no sales tone",
}
PART_KEY = {"short": "short_30s", "deep": "deep_dive"}
UA = {"User-Agent": "kiezwalk-tuebingen-tool/1"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# --- Bundle ----------------------------------------------------------------
def load():
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def save(d):
    BUNDLE.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def cards(d, lang=None):
    for pid, p in d["packages"].items():
        if lang and not pid.endswith("-" + lang):
            continue
        for c in p["factCards"]:
            yield pid, c


def find(d, cid):
    hits = [(pid, c) for pid, c in cards(d) if c["id"] == cid]
    if not hits:
        sys.exit(f"Karte {cid} nicht gefunden.")
    return hits


# --- Windows Credential Manager (Gemini-Schlüssel) --------------------------
if os.name == "nt":
    from ctypes import wintypes

    class _CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def _cred_write(secret):
    blob = secret.encode("utf-16-le")
    buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    c = _CRED(Type=1, TargetName=CRED_TARGET, CredentialBlobSize=len(blob),
              CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)), Persist=2, UserName="gemini")
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(c), 0):
        raise OSError("Speichern in der Anmeldeinformationsverwaltung fehlgeschlagen")


def _cred_read():
    if os.name != "nt":
        return None
    p = ctypes.POINTER(_CRED)()
    if not ctypes.windll.advapi32.CredReadW(CRED_TARGET, 1, 0, ctypes.byref(p)):
        return None
    try:
        return ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize).decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(p)


def gemini_key():
    key = _cred_read() or os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Kein Gemini-Schlüssel. Einmalig: python tools/kiezwalk.py setup-key")
    return key.strip()


# --- Medien ----------------------------------------------------------------
def _media_name(prefix, data, ext):
    return f"{prefix}-{hashlib.sha256(data).hexdigest()[:10]}.{ext}"


def _wav_from_pcm(pcm, rate=24000):
    import io
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return b.getvalue()


def synthesize(text, lang):
    body = {"model": TTS_MODEL,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": text,
                       "annotations": [{"type": "speech_metadata", "style": STYLE.get(lang, STYLE["de"])}]}]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": VOICE}]}}
    req = urllib.request.Request(TTS_ENDPOINT, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-goog-api-key": gemini_key(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        if e.code == 429:
            sys.exit("Gemini-Kontingent erschöpft (429). Pausieren: 1 Minute (Minutenlimit) bzw. bis morgen (Tageslimit).\n" + detail)
        sys.exit(f"Gemini-Fehler {e.code}:\n{detail}")
    audio = None
    for step in resp.get("steps", []):
        for item in step.get("content") or []:
            if item.get("type") == "audio" and item.get("data"):
                audio = item["data"]
    audio = audio or (resp.get("output_audio") or {}).get("data")
    if not audio:
        sys.exit("Antwort ohne Audio: " + json.dumps(resp)[:500])
    data = base64.b64decode(audio)
    return data if data.startswith(b"RIFF") else _wav_from_pcm(data)


def cmd_tts(a):
    d = load()
    part_key = PART_KEY[a.part]
    done = None  # dieselbe Karte steckt evtl. auch im Tourist-Paket (weekend) – nur einmal vertonen
    for pid, c in find(d, a.card):
        if done:
            c.setdefault("audio_assets", {})[part_key] = copy.deepcopy(done)
            continue
        lang = c.get("language") or pid.rsplit("-", 1)[-1]
        body = c["deep_dive_text"] if a.part == "deep" else c["short_description"]
        if not (body or "").strip():
            sys.exit(f"{c['id']}: kein Text für {a.part}.")
        text = f"{c['title'].strip()}.\n\n{body.strip()}" if a.part == "short" else body.strip()
        wav = synthesize(text, lang)
        tmp = ROOT / "media" / "audio" / "_tmp.wav"
        tmp.write_bytes(wav)
        with wave.open(str(tmp), "rb") as w:
            secs = round(w.getnframes() / float(w.getframerate()), 1)
        ext, data = "wav", wav
        ff = shutil.which("ffmpeg")
        if ff:
            mp3 = tmp.with_suffix(".mp3")
            subprocess.run([ff, "-v", "error", "-y", "-i", str(tmp), "-b:a", "96k", str(mp3)], check=True)
            ext, data = "mp3", mp3.read_bytes()
            mp3.unlink()
        tmp.unlink()
        name = _media_name(f"{c['id']}-{a.part}", data, ext)
        (ROOT / "media" / "audio" / name).write_bytes(data)
        c.setdefault("audio_assets", {})[part_key] = {
            "length": part_key, "url": MEDIA_BASE + "audio/" + name, "duration_seconds": secs,
            "transcript": text, "voice_profile": TTS_MODEL, "file_format": ext, "voice_label": VOICE}
        done = c["audio_assets"][part_key]
        print(f"OK {c['id']} {a.part}: media/audio/{name} ({secs} s){'' if ff else '  – WAV, weil ffmpeg fehlt'}")
    save(d)


def cmd_add_image(a):
    src = Path(a.file)
    ext = src.suffix.lower().lstrip(".").replace("jpeg", "jpg")
    if ext not in ("webp", "jpg", "png"):
        sys.exit("Nur .webp, .jpg oder .png.")
    data = src.read_bytes()
    if len(data) > 1_500_000:
        sys.exit("Bild > 1,5 MB – bitte vorher verkleinern (max. 1600 px Breite).")
    d = load()
    base_id = a.card.rsplit("-", 1)[0]
    name = _media_name(base_id, data, ext)
    (ROOT / "media" / "images" / name).write_bytes(data)
    for _, c in find(d, a.card) + ([] if a.only_this else
                                   [h for h in cards(d) if h[1]["id"] != a.card and h[1]["id"].rsplit("-", 1)[0] == base_id]):
        imgs = c.setdefault("images", [])
        kind = a.kind if not any(i.get("kind") == "titel" for i in imgs) or a.kind != "titel" else "detail"
        imgs.append({"id": f"{c['id']}-{len(imgs)}", "kind": kind, "url": MEDIA_BASE + "images/" + name,
                     "caption": a.caption, "credit": a.credit, "license": a.license, "license_url": a.license_url,
                     "source_url": a.source_url, "generated": bool(a.generated)})
        c["imageMissing"] = False
        print(f"OK {c['id']}: media/images/{name} ({kind})")
    save(d)


def cmd_new_card(a):
    d = load()
    pid = f"tuebingen-stadtgebiet-{a.lang}"
    if pid not in d["packages"]:
        sys.exit(f"Paket {pid} fehlt.")
    cid = f"tuebingen-{a.slug}-{a.lang}"
    if any(c["id"] == cid for _, c in cards(d)):
        sys.exit(f"{cid} existiert schon.")
    pkg = d["packages"][pid]["factCards"]
    tpl = copy.deepcopy(next((c for c in pkg if c.get("category") == a.category), pkg[0]))
    sources = json.loads(Path(a.sources_file).read_text(encoding="utf-8")) if a.sources_file else []
    for i, s in enumerate(sources):
        s.setdefault("id", "source-" + hashlib.sha256((s.get("url", "") + str(i)).encode()).hexdigest()[:12])
        s.setdefault("retrieved_at", datetime.now(timezone.utc).isoformat())
    now = datetime.now(timezone.utc).isoformat()
    tpl.update({"id": cid, "title": a.title, "short_description": Path(a.short_file).read_text(encoding="utf-8").strip(),
                "deep_dive_text": Path(a.deep_file).read_text(encoding="utf-8").strip() if a.deep_file else "",
                "lat": a.lat, "lng": a.lng, "radius_m": a.radius, "tags": a.tags or [], "category": a.category,
                "sources": sources, "source_count": len(sources), "language": a.lang, "city_id": "tuebingen",
                "created_by": "melanie", "updated_at": now, "images": [], "imageMissing": True,
                "editorial_status": "published", "verification_status": "sourced" if sources else "unsourced",
                "audio_assets": {k: {"length": k, "url": "", "duration_seconds": 0, "transcript": "",
                                     "voice_profile": "", "file_format": "mp3", "voice_label": ""}
                                 for k in ("short_30s", "deep_dive")}})
    if a.display_category:
        tpl["display_category"] = a.display_category
    pkg.append(tpl)
    save(d)
    print(f"OK neue Karte {cid} in {pid}")


def cmd_list(a):
    for pid, c in cards(load(), a.lang):
        aud = "".join("A" if (c.get("audio_assets") or {}).get(k, {}).get("url") else "-" for k in ("short_30s", "deep_dive"))
        print(f"{c['id']:52} {aud} img:{len(c.get('images') or [])}  {c['title']}")


def cmd_show(a):
    for pid, c in find(load(), a.card):
        c = {k: v for k, v in c.items()}
        c["images"] = [{**i, "url": i["url"][:60]} for i in c.get("images") or []]
        print(pid); print(json.dumps(c, ensure_ascii=False, indent=1))


def cmd_validate(a=None):
    raw = BUNDLE.read_bytes()
    prev = None
    try:
        prev = card_count(_get(LIVE_URL))
    except Exception:
        pass
    errs = validate(raw, prev)
    for f in (ROOT / "media").rglob("*"):
        if f.is_file() and f.name != ".gitkeep" and f.stat().st_size > 20_000_000:
            errs.append(f"Mediendatei zu groß: {f}")
    if errs:
        print("FEHLER:"); [print(" -", e) for e in errs]
        sys.exit(1)
    print(f"OK gültig ({card_count(raw)} Karten, {len(raw)/1e6:.1f} MB)")


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url + f"?v={time.time_ns()}", headers=UA), timeout=60) as r:
        return r.read()


def _git(*args, capture=False):
    r = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=capture)
    if r.returncode:
        sys.exit(f"git {' '.join(args)} fehlgeschlagen:\n{(r.stderr or '')[-800:]}")
    return (r.stdout or "").strip()


def cmd_publish(a):
    cmd_validate()
    _git("add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        _git("commit", "-m", a.message)
    _git("pull", "--rebase", "origin", "main")
    _git("push", "origin", "HEAD:main")
    sha = _git("rev-parse", "HEAD", capture=True)
    print(f"Gepusht {sha[:10]}. Der Server prüft und stellt live (meist 5–15 min).")
    if not a.no_wait:
        _wait(sha, 1800)


def _status(sha):
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/commits/{sha}/status", headers=UA), timeout=30) as r:
            st = json.loads(r.read())
        s = [x for x in st.get("statuses", []) if x.get("context") == "kiezwalk/live"]
        return (s[0]["state"], s[0].get("description", "")) if s else ("pending", "noch nicht abgeholt")
    except Exception as e:
        return ("unknown", str(e))


def _wait(sha, timeout):
    want = hashlib.sha256(BUNDLE.read_bytes()).hexdigest()
    end = time.time() + timeout
    while time.time() < end:
        state, desc = _status(sha)
        live = hashlib.sha256(_get(LIVE_URL)).hexdigest()
        if live == want:
            print("LIVE ✓  https://kiezwalk.com/tuebingen"); return
        if state in ("failure", "error"):
            sys.exit(f"Server hat abgelehnt: {desc}")
        print(f"… warte ({state}: {desc})"); time.sleep(60)
    sys.exit("Nach 30 min noch nicht live – später `python tools/kiezwalk.py status` ausführen.")


def cmd_status(a):
    sha = _git("rev-parse", "HEAD", capture=True)
    want = hashlib.sha256(BUNDLE.read_bytes()).hexdigest()
    live = hashlib.sha256(_get(LIVE_URL)).hexdigest()
    state, desc = _status(sha)
    print(f"Commit {sha[:10]}: Server {state} – {desc}")
    print("Live == lokal ✓" if live == want else "Live weicht vom lokalen Stand ab.")


def cmd_setup_key(a):
    secret = getpass.getpass("Gemini-API-Schlüssel einfügen (Eingabe unsichtbar): ").strip()
    if not secret:
        sys.exit("Nichts eingegeben.")
    _cred_write(secret)
    print(f"Gespeichert in der Windows-Anmeldeinformationsverwaltung ('{CRED_TARGET}').")


def main():
    ap = argparse.ArgumentParser(description="KiezWalk Tübingen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup-key").set_defaults(f=cmd_setup_key)
    p = sub.add_parser("list"); p.add_argument("--lang", choices=["de", "en"]); p.set_defaults(f=cmd_list)
    p = sub.add_parser("show"); p.add_argument("card"); p.set_defaults(f=cmd_show)
    p = sub.add_parser("tts"); p.add_argument("card"); p.add_argument("--part", choices=["short", "deep"], default="short"); p.set_defaults(f=cmd_tts)
    p = sub.add_parser("add-image")
    p.add_argument("card"); p.add_argument("file")
    for k in ("caption", "credit", "license", "license_url", "source_url"):
        p.add_argument("--" + k.replace("_", "-"), dest=k, required=True)
    p.add_argument("--kind", default="titel", choices=["titel", "heute", "damals", "detail"])
    p.add_argument("--generated", action="store_true", help="KI-Illustration (wird gekennzeichnet)")
    p.add_argument("--only-this", action="store_true", help="nur diese Sprachfassung, nicht DE+EN")
    p.set_defaults(f=cmd_add_image)
    p = sub.add_parser("new-card")
    p.add_argument("--slug", required=True, help="z. B. stocherkahn-steg (ohne tuebingen- und -de)")
    p.add_argument("--lang", required=True, choices=["de", "en"])
    p.add_argument("--title", required=True)
    p.add_argument("--short-file", required=True); p.add_argument("--deep-file")
    p.add_argument("--lat", type=float, required=True); p.add_argument("--lng", type=float, required=True)
    p.add_argument("--radius", type=int, default=60)
    p.add_argument("--category", required=True); p.add_argument("--display-category")
    p.add_argument("--tags", nargs="*"); p.add_argument("--sources-file", help="JSON-Liste [{title,url,publisher,source_type}]")
    p.set_defaults(f=cmd_new_card)
    sub.add_parser("validate").set_defaults(f=cmd_validate)
    p = sub.add_parser("publish"); p.add_argument("-m", "--message", required=True); p.add_argument("--no-wait", action="store_true"); p.set_defaults(f=cmd_publish)
    sub.add_parser("status").set_defaults(f=cmd_status)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
