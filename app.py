from __future__ import annotations

import os
import random
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional

import requests
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string,
    jsonify,
    session,
    abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

APP = Flask(__name__)

# ✅ ONLINE: SECRET_KEY als Env setzen (Koyeb -> Secrets -> SECRET_KEY)
APP.secret_key = os.environ.get("SECRET_KEY", "CHANGE_ME_LOCAL_ONLY")

DB_PATH = Path("app.db")

# Admin seed
ADMIN_USERNAME = "i3mad"
ADMIN_START_PASSWORD = "123456"  # bitte nach dem ersten Login ändern

# Spam/Abuse Schutz (einfach, aber effektiv)
RATE_LIMITS = {
    "login": (12, 600),        # 12 / 10 min
    "register": (6, 600),      # 6 / 10 min
    "city_search": (40, 60),   # 40 / 1 min
    "favorite": (60, 60),
    "track_done": (40, 60),
}

_RATE_BUCKET: dict[tuple[str, str], list[float]] = {}
_FAILED_LOGINS: dict[tuple[str, str], dict[str, float]] = {}
LOCKOUT_FAILS = 8
LOCKOUT_WINDOW = 600
LOCKOUT_TIME = 600


def client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(endpoint_name: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = client_ip()
            key = (endpoint_name, ip)
            now = time.time()
            max_req, win = RATE_LIMITS.get(endpoint_name, (999999, 1))
            bucket = _RATE_BUCKET.get(key, [])
            bucket = [t for t in bucket if now - t <= win]
            if len(bucket) >= max_req:
                return ("Too many requests. Please wait a bit.", 429)
            bucket.append(now)
            _RATE_BUCKET[key] = bucket
            return fn(*args, **kwargs)
        return wrapper
    return deco


def lockout_check(username: str) -> Optional[str]:
    ip = client_ip()
    key = (ip, username.lower())
    now = time.time()
    state = _FAILED_LOGINS.get(key)
    if not state:
        return None
    locked_until = state.get("locked_until", 0.0)
    if locked_until and now < locked_until:
        remaining = int(locked_until - now)
        return f"Locked for {remaining}s due to too many failed logins."
    return None


def lockout_fail(username: str):
    ip = client_ip()
    key = (ip, username.lower())
    now = time.time()
    state = _FAILED_LOGINS.get(key, {"count": 0, "first": now, "locked_until": 0})
    if now - state.get("first", now) > LOCKOUT_WINDOW:
        state = {"count": 0, "first": now, "locked_until": 0}

    state["count"] = state.get("count", 0) + 1
    if state["count"] >= LOCKOUT_FAILS:
        state["locked_until"] = now + LOCKOUT_TIME
        state["count"] = 0
        state["first"] = now
    _FAILED_LOGINS[key] = state


def lockout_success(username: str):
    ip = client_ip()
    key = (ip, username.lower())
    if key in _FAILED_LOGINS:
        del _FAILED_LOGINS[key]


LANGS = [
    ("bs", "Bosanski"),
    ("de", "Deutsch"),
    ("en", "English"),
    ("tr", "Türkçe"),
    ("ar", "العربية"),
    ("fr", "Français"),
    ("it", "Italiano"),
    ("es", "Español"),
    ("sq", "Shqip"),
]

T: dict[str, dict[str, str]] = {
    "de": {
        "app_name": "Islam WebApp",
        "tagline": "Gebete • Quran • Tracker",
        "home": "Start",
        "prayer_times": "Gebetszeiten",
        "tracker": "Tracker",
        "quran": "Quran",
        "favorites": "Favoriten",
        "settings": "Einstellungen",
        "admin": "Admin",
        "login": "Login",
        "logout": "Logout",
        "register": "Registrieren",
        "username": "Benutzername",
        "password": "Passwort",
        "password2": "Passwort wiederholen",
        "invite_code": "Invite Code",
        "save": "Speichern",
        "city": "Stadt",
        "country": "Land",
        "method": "Methode",
        "language": "Sprache",
        "theme": "Theme",
        "dark": "Dunkel",
        "light": "Hell",
        "auto": "Auto",
        "next_prayer": "Nächstes Gebet",
        "remaining": "Noch",
        "timezone": "Zeitzone",
        "today": "Heute",
        "progress_today": "Fortschritt heute",
        "mark_done": "Als erledigt markieren",
        "done": "erledigt",
        "streak": "Streak",
        "streak_desc": "Tage mit allen 5 Gebeten",
        "last_7_days": "Letzte 7 Tage",
        "last_entries": "Letzte Einträge",
        "date": "Datum",
        "time": "Zeit",
        "completed": "Erledigt",
        "no_entries": "Noch nichts eingetragen.",
        "quran_search": "Quran Suche",
        "search": "Suche",
        "search_placeholder": "Suche z.B. barmherzig / mercy / rahma",
        "no_results": "Keine Treffer gefunden.",
        "surah": "Sura",
        "surahs": "Suren",
        "arabic": "Arabisch",
        "translation": "Übersetzung",
        "back": "Zurück",
        "showing_first_60": "Aktuell: erste 60 Verse (Paging kommt später).",
        "verse_of_day": "Vers des Tages",
        "quick_actions": "Schnellzugriff",
        "open_settings": "Einstellungen öffnen",
        "pick_city": "City Suche tippen",
        "pick_city_hint": "Tippe z.B. „Sarajevo“ oder „Wels“ und wähle aus.",
        "error": "Fehler",
        "error_prayer_load": "Fehler beim Laden der Gebetszeiten",
        "remove": "Entfernen",
        "added": "Hinzugefügt",
        "no_favorites": "Noch keine Favoriten.",
        "favorites_tip": "Klicke „⭐ Entfernen“, um einen Favoriten zu löschen.",
        "current_settings": "Aktuelle Einstellungen",
        "saved_ok": "Gespeichert!",
        "auth_required": "Bitte einloggen, um das zu nutzen.",
        "register_disabled": "Registrierung ist deaktiviert.",
        "admin_panel": "Admin Dashboard",
        "users": "User",
        "role": "Rolle",
        "created": "Erstellt",
        "status": "Status",
        "active": "Aktiv",
        "blocked": "Gesperrt",
        "block": "Sperren",
        "unblock": "Entsperren",
        "make_admin": "Zum Admin machen",
        "make_user": "Zum User machen",
        "site_settings": "Site Settings",
        "allow_register": "Registrierung erlauben",
        "invite_codes": "Invite Codes (Komma getrennt)",
        "yes": "Ja",
        "no": "Nein",
        "change_admin_pass": "Admin Passwort ändern",
        "new_password": "Neues Passwort",
        "update": "Update",
        "invalid_login": "Login falsch.",
        "username_taken": "Benutzername existiert schon.",
        "password_mismatch": "Passwörter stimmen nicht überein.",
        "password_too_short": "Passwort zu kurz (min. 8).",
        "bad_username": "Username ungültig (nur Buchstaben/Zahlen/._- und 3–24 Zeichen).",
        "bot_blocked": "Bot erkannt. Bitte nochmal.",
        "invite_wrong": "Invite Code falsch.",
    },
    "en": {
        "app_name": "Islam WebApp",
        "tagline": "Prayers • Quran • Tracker",
        "home": "Home",
        "prayer_times": "Prayer Times",
        "tracker": "Tracker",
        "quran": "Quran",
        "favorites": "Favorites",
        "settings": "Settings",
        "admin": "Admin",
        "login": "Login",
        "logout": "Logout",
        "register": "Register",
        "username": "Username",
        "password": "Password",
        "password2": "Repeat password",
        "invite_code": "Invite Code",
        "save": "Save",
        "city": "City",
        "country": "Country",
        "method": "Method",
        "language": "Language",
        "theme": "Theme",
        "dark": "Dark",
        "light": "Light",
        "auto": "Auto",
        "next_prayer": "Next prayer",
        "remaining": "Remaining",
        "timezone": "Timezone",
        "today": "Today",
        "progress_today": "Today's progress",
        "mark_done": "Mark as done",
        "done": "done",
        "streak": "Streak",
        "streak_desc": "days with all 5 prayers",
        "last_7_days": "Last 7 days",
        "last_entries": "Latest entries",
        "date": "Date",
        "time": "Time",
        "completed": "Completed",
        "no_entries": "No entries yet.",
        "quran_search": "Quran Search",
        "search": "Search",
        "search_placeholder": "Search e.g. mercy / rahma",
        "no_results": "No results found.",
        "surah": "Surah",
        "surahs": "Surahs",
        "arabic": "Arabic",
        "translation": "Translation",
        "back": "Back",
        "showing_first_60": "Currently: first 60 verses (paging later).",
        "verse_of_day": "Verse of the day",
        "quick_actions": "Quick actions",
        "open_settings": "Open settings",
        "pick_city": "City search (type)",
        "pick_city_hint": "Type “Sarajevo” or “Wels” and pick.",
        "error": "Error",
        "error_prayer_load": "Failed to load prayer times",
        "remove": "Remove",
        "added": "Added",
        "no_favorites": "No favorites yet.",
        "favorites_tip": "Click “⭐ Remove” to delete a favorite.",
        "current_settings": "Current settings",
        "saved_ok": "Saved!",
        "auth_required": "Please login to use this feature.",
        "register_disabled": "Registration is disabled.",
        "admin_panel": "Admin Dashboard",
        "users": "Users",
        "role": "Role",
        "created": "Created",
        "status": "Status",
        "active": "Active",
        "blocked": "Blocked",
        "block": "Block",
        "unblock": "Unblock",
        "make_admin": "Make admin",
        "make_user": "Make user",
        "site_settings": "Site settings",
        "allow_register": "Allow registration",
        "invite_codes": "Invite codes (comma separated)",
        "yes": "Yes",
        "no": "No",
        "change_admin_pass": "Change admin password",
        "new_password": "New password",
        "update": "Update",
        "invalid_login": "Invalid login.",
        "username_taken": "Username already exists.",
        "password_mismatch": "Passwords do not match.",
        "password_too_short": "Password too short (min 8).",
        "bad_username": "Bad username (only letters/numbers/._- and 3–24 chars).",
        "bot_blocked": "Bot detected. Try again.",
        "invite_wrong": "Wrong invite code.",
    },
}

def _ensure_lang(code: str):
    if code not in T:
        T[code] = dict(T["en"])

for code, _ in LANGS:
    _ensure_lang(code)

def tr(lang: str, key: str) -> str:
    lang = lang if lang in T else "en"
    return T[lang].get(key, T["en"].get(key, key))


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        is_blocked INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
      )
    """)

    cur.execute("""
      CREATE TABLE IF NOT EXISTS site_settings (
        k TEXT PRIMARY KEY,
        v TEXT NOT NULL
      )
    """)

    cur.execute("""
      CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER NOT NULL,
        k TEXT NOT NULL,
        v TEXT NOT NULL,
        PRIMARY KEY(user_id, k)
      )
    """)

    cur.execute("""
      CREATE TABLE IF NOT EXISTS prayers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        city TEXT NOT NULL,
        country TEXT NOT NULL,
        prayer TEXT NOT NULL,
        done_at TEXT NOT NULL
      )
    """)

    cur.execute("""
      CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        verse_key TEXT NOT NULL,
        added_at TEXT NOT NULL,
        UNIQUE(user_id, verse_key)
      )
    """)

    # Settings defaults
    cur.execute("INSERT OR IGNORE INTO site_settings(k,v) VALUES('allow_register','1')")
    cur.execute("INSERT OR IGNORE INTO site_settings(k,v) VALUES('invite_codes','i3mad2026')")

    # Seed admin
    cur.execute("SELECT id FROM users WHERE username=?", (ADMIN_USERNAME,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users(username,password_hash,role,is_blocked,created_at) VALUES(?,?,?,?,?)",
            (
                ADMIN_USERNAME,
                generate_password_hash(ADMIN_START_PASSWORD),
                "admin",
                0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    conn.commit()
    conn.close()


def get_site_setting(k: str, default: str) -> str:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT v FROM site_settings WHERE k=?", (k,))
    row = cur.fetchone()
    conn.close()
    return row["v"] if row else default


def set_site_setting(k: str, v: str):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO site_settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (k, v),
    )
    conn.commit()
    conn.close()


def current_user() -> Optional[sqlite3.Row]:
    uid = session.get("user_id")
    if not uid:
        return None
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    u = cur.fetchone()
    conn.close()
    if u and u["is_blocked"] == 1:
        session.pop("user_id", None)
        return None
    return u


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("login", next=request.path))
        if u["role"] != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


DEFAULT_USER_SETTINGS = {
    "lang": "bs",
    "city": "Wels",
    "country": "Austria",
    "method": "3",
    "theme": "auto",
}


def get_user_settings(uid: Optional[int]) -> dict[str, str]:
    if uid:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT k,v FROM user_settings WHERE user_id=?", (uid,))
        rows = cur.fetchall()
        conn.close()
        s = {r["k"]: r["v"] for r in rows}
        for k, v in DEFAULT_USER_SETTINGS.items():
            s.setdefault(k, v)
        return s
    s = session.get("anon_settings") or {}
    out = dict(DEFAULT_USER_SETTINGS)
    out.update({k: str(v) for k, v in s.items()})
    return out


def set_user_setting(uid: Optional[int], k: str, v: str):
    if uid:
        conn = db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_settings(user_id,k,v) VALUES(?,?,?) "
            "ON CONFLICT(user_id,k) DO UPDATE SET v=excluded.v",
            (uid, k, v),
        )
        conn.commit()
        conn.close()
    else:
        s = session.get("anon_settings") or {}
        s[k] = v
        session["anon_settings"] = s


PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]


def today_str() -> str:
    return date.today().isoformat()


def parse_hhmm(s: str):
    if not s:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def fetch_prayer_times(city: str, country: str, method: str):
    url = "https://api.aladhan.com/v1/timingsByCity"
    params = {"city": city, "country": country, "method": method}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()["data"]
    timings = data["timings"]
    meta = data.get("meta") or {}
    tz = meta.get("timezone") or "Europe/Vienna"
    out = {k: timings.get(k) for k in PRAYERS}
    return out, tz


def compute_next_prayer(city: str, country: str, method: str):
    timings, tz_name = fetch_prayer_times(city, country, method)
    if ZoneInfo:
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
    else:
        tz = None
        now = datetime.now()

    today = now.date()
    candidates = []
    for p in PRAYERS:
        hhmm = parse_hhmm(timings.get(p, ""))
        if not hhmm:
            continue
        h, m = hhmm
        dt = datetime(today.year, today.month, today.day, h, m, tzinfo=tz) if tz else datetime(today.year, today.month, today.day, h, m)
        candidates.append((p, dt))
    candidates.sort(key=lambda x: x[1])

    for p, dt in candidates:
        if dt > now:
            return timings, tz_name, p, dt.isoformat()

    hhmm = parse_hhmm(timings.get("Fajr", ""))
    if hhmm:
        h, m = hhmm
        tomorrow = today + timedelta(days=1)
        dt = datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, tzinfo=tz) if tz else datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m)
        return timings, tz_name, "Fajr", dt.isoformat()

    return timings, tz_name, None, None


def done_today_set(uid: int) -> set[str]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT prayer FROM prayers WHERE user_id=? AND day=? GROUP BY prayer", (uid, today_str()))
    s = {r["prayer"] for r in cur.fetchall()}
    conn.close()
    return s


def compute_streak(uid: int) -> int:
    today_d = date.today()
    start = (today_d - timedelta(days=180)).isoformat()
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT day, prayer FROM prayers WHERE user_id=? AND day>=? ORDER BY day ASC", (uid, start))
    rows = cur.fetchall()
    conn.close()

    m: dict[str, set[str]] = {}
    for r in rows:
        m.setdefault(r["day"], set()).add(r["prayer"])

    streak = 0
    d = today_d
    while True:
        ds = d.isoformat()
        if ds in m and all(p in m[ds] for p in PRAYERS):
            streak += 1
            d = d - timedelta(days=1)
        else:
            break
    return streak


def get_favorites_set(uid: int) -> set[str]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT verse_key FROM favorites WHERE user_id=?", (uid,))
    s = {r["verse_key"] for r in cur.fetchall()}
    conn.close()
    return s


def toggle_favorite(uid: int, verse_key: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM favorites WHERE user_id=? AND verse_key=?", (uid, verse_key))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("DELETE FROM favorites WHERE user_id=? AND verse_key=?", (uid, verse_key))
    else:
        cur.execute(
            "INSERT OR IGNORE INTO favorites(user_id, verse_key, added_at) VALUES(?,?,?)",
            (uid, verse_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    conn.commit()
    conn.close()


def search_city_nominatim(q: str):
    if not q or len(q.strip()) < 2:
        return []
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "json", "addressdetails": 1, "limit": 8}
    headers = {"User-Agent": "IslamWebApp/1.0 (public demo)"}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    out = []
    for it in data:
        addr = it.get("address") or {}
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or it.get("display_name", "").split(",")[0]
        country = addr.get("country") or ""
        label = it.get("display_name") or f"{city}, {country}"
        if city and country:
            out.append({"city": city, "country": country, "label": label})
    seen = set()
    uniq = []
    for x in out:
        key = (x["city"].lower(), x["country"].lower())
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq


def verse_of_day(lang: str):
    tr_ed = "en.sahih"
    if lang == "de":
        tr_ed = "de.aburida"
    ayah_num = random.randint(1, 6236)
    try:
        a_ar = requests.get(f"https://api.alquran.cloud/v1/ayah/{ayah_num}/quran-uthmani", timeout=15).json()["data"]
        a_tr = requests.get(f"https://api.alquran.cloud/v1/ayah/{ayah_num}/{tr_ed}", timeout=15).json()["data"]
        ref = f"{a_ar.get('surah', {}).get('number', '?')}:{a_ar.get('numberInSurah', '?')}"
        return {"ref": ref, "ar": a_ar.get("text", ""), "tr": a_tr.get("text", "")}
    except Exception:
        return {"ref": "-", "ar": "", "tr": ""}


BASE = r"""
<!doctype html>
<html lang="{{ lang }}" data-theme-server="{{ theme }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{{ title }}</title>
  <style>
    :root{--bg:#0b0f14;--card:rgba(255,255,255,.06);--text:#e8eef7;--muted:rgba(232,238,247,.68);
      --border:rgba(255,255,255,.10);--shadow:0 10px 30px rgba(0,0,0,.25);
      --accent:#6ea8ff;--ok:#69d18d;--radius:16px;--pad:16px;--max:1120px;}
    [data-theme="light"]{--bg:#f6f7fb;--card:#fff;--text:#0f172a;--muted:rgba(15,23,42,.65);
      --border:rgba(15,23,42,.10);--shadow:0 10px 30px rgba(15,23,42,.08);--accent:#2563eb;--ok:#15803d;}
    *{box-sizing:border-box}
    body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
      background:radial-gradient(1200px 700px at 20% 0%, rgba(110,168,255,.18), transparent 55%),
                 radial-gradient(900px 500px at 80% 10%, rgba(105,209,141,.16), transparent 55%), var(--bg);
      color:var(--text);}
    .wrap{max-width:var(--max);margin:0 auto;padding:18px;}
    .topbar{position:sticky;top:0;backdrop-filter:blur(10px);
      background:color-mix(in srgb,var(--bg) 78%,transparent);border-bottom:1px solid var(--border);z-index:10;}
    .nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;max-width:var(--max);margin:0 auto;flex-wrap:wrap;}
    .brand{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:.4px;}
    .logo{width:34px;height:34px;border-radius:12px;background:linear-gradient(135deg, rgba(110,168,255,.95), rgba(105,209,141,.92));box-shadow:var(--shadow);}
    .links{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
    a{color:var(--text);text-decoration:none;opacity:.92;}
    a:hover{opacity:1;color:var(--accent)}
    .pill{display:inline-flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--border);border-radius:999px;
      background:color-mix(in srgb,var(--card) 85%,transparent);}
    .btn{display:inline-flex;align-items:center;justify-content:center;padding:10px 12px;border-radius:999px;border:1px solid var(--border);
      background:color-mix(in srgb,var(--card) 85%,transparent);color:var(--text);cursor:pointer;}
    .btn:hover{border-color:color-mix(in srgb,var(--accent) 45%,var(--border));}
    .muted{color:var(--muted)}
    .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:var(--pad);box-shadow:var(--shadow);margin:14px 0;}
    .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;}
    .col-6{grid-column:span 6}.col-4{grid-column:span 4}.col-8{grid-column:span 8}.col-12{grid-column:span 12}
    @media (max-width:900px){.col-6,.col-4,.col-8{grid-column:span 12}}
    .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;}
    input,select{padding:12px 12px;border-radius:12px;border:1px solid var(--border);
      background:color-mix(in srgb,var(--card) 92%,transparent);color:var(--text);outline:none;min-width:180px;}
    table{border-collapse:collapse;width:100%;}
    th,td{border-bottom:1px solid var(--border);padding:12px 10px;text-align:left;}
    .ok{color:var(--ok);font-weight:800;}
    .badge{display:inline-flex;padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:color-mix(in srgb,var(--card) 85%,transparent);}
    .listbox{margin-top:10px;border:1px solid var(--border);border-radius:12px;overflow:hidden;}
    .listbox button{width:100%;text-align:left;padding:10px 12px;border:0;background:color-mix(in srgb,var(--card) 92%,transparent);color:var(--text);cursor:pointer;}
    .listbox button:hover{background:color-mix(in srgb,var(--card) 75%,transparent);}
    .danger{border-color:color-mix(in srgb, red 40%, var(--border));}
    .hiddenhp{position:absolute;left:-9999px;top:-9999px;height:1px;width:1px;opacity:0;}
    .hamburger{display:none}
    @media (max-width:760px){
      .links{display:none;width:100%;padding-top:10px;}
      .links.open{display:flex;}
      .hamburger{display:inline-flex}
      input,select{min-width:100%;}
    }
    .small{font-size:12px}
    .big{font-size:28px;font-weight:900}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="nav">
      <div class="brand">
        <div class="logo"></div>
        <div>
          <div style="line-height:1.1;">{{ tr(lang,'app_name') }}</div>
          <div class="muted" style="font-size:12px;margin-top:2px;">{{ tr(lang,'tagline') }}</div>
        </div>
      </div>

      <div class="row" style="gap:10px;">
        <button class="btn hamburger" id="menuBtn" type="button" aria-label="Menu">☰</button>
        <button class="btn" id="themeBtn" type="button" title="Theme">🌙</button>

        <a class="pill" href="{{ url_for('settings') }}">⚙ {{ tr(lang,'settings') }}</a>

        {% if user %}
          {% if user_role == 'admin' %}
            <a class="pill" href="{{ url_for('admin_panel') }}">🛡 {{ tr(lang,'admin') }}</a>
          {% endif %}
          <a class="pill" href="{{ url_for('logout') }}">↩ {{ tr(lang,'logout') }}</a>
        {% else %}
          <a class="pill" href="{{ url_for('login') }}">🔐 {{ tr(lang,'login') }}</a>
        {% endif %}
      </div>

      <div class="links" id="navLinks">
        <a class="pill" href="{{ url_for('home') }}">{{ tr(lang,'home') }}</a>
        <a class="pill" href="{{ url_for('prayer_times') }}">{{ tr(lang,'prayer_times') }}</a>
        <a class="pill" href="{{ url_for('quran') }}">{{ tr(lang,'quran') }}</a>
        <a class="pill" href="{{ url_for('quran_search') }}">🔎 {{ tr(lang,'search') }}</a>
        <a class="pill" href="{{ url_for('tracker') }}">{{ tr(lang,'tracker') }}</a>
        <a class="pill" href="{{ url_for('favorites') }}">{{ tr(lang,'favorites') }}</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    {{ body|safe }}
  </div>

  <script>
    (function () {
      const root = document.documentElement;
      function updateThemeIcon() {
        const btn = document.getElementById("themeBtn");
        if (!btn) return;
        const t = root.getAttribute("data-theme") || "dark";
        btn.textContent = (t === "light") ? "☀️" : "🌙";
      }
      function setTheme(theme) {
        root.setAttribute("data-theme", theme);
        localStorage.setItem("theme", theme);
        updateThemeIcon();
      }
      function initTheme() {
        const serverTheme = root.getAttribute("data-theme-server") || "auto";
        const stored = localStorage.getItem("theme");
        if (stored) root.setAttribute("data-theme", stored);
        else if (serverTheme === "auto") {
          const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
          root.setAttribute("data-theme", prefersLight ? "light" : "dark");
        } else root.setAttribute("data-theme", serverTheme);
        updateThemeIcon();
        const btn = document.getElementById("themeBtn");
        if (btn) btn.addEventListener("click", function () {
          const current = root.getAttribute("data-theme") || "dark";
          setTheme(current === "light" ? "dark" : "light");
        });
      }
      function initMenu() {
        const menuBtn = document.getElementById("menuBtn");
        const navLinks = document.getElementById("navLinks");
        if (menuBtn && navLinks) menuBtn.addEventListener("click", () => navLinks.classList.toggle("open"));
      }
      document.addEventListener("DOMContentLoaded", () => { initTheme(); initMenu(); });
    })();
  </script>
</body>
</html>
"""

def render_page(title: str, body_html: str):
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s.get("lang", "en")
    theme = s.get("theme", "auto")
    return render_template_string(
        BASE,
        title=title,
        body=body_html,
        lang=lang,
        theme=theme,
        tr=tr,
        user=(u is not None),
        user_role=(u["role"] if u else "user"),
        url_for=url_for,
    )

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,24}$")
def valid_username(u: str) -> bool:
    return bool(USERNAME_RE.match(u or ""))


@APP.get("/login")
def login():
    if current_user():
        return redirect(url_for("home"))
    s = get_user_settings(None)
    lang = s["lang"]
    next_url = request.args.get("next") or url_for("home")

    body = f"""
    <div class="card col-6">
      <h2 style="margin-top:0;">🔐 {tr(lang,'login')}</h2>
      <form method="post" action="{url_for('login_post')}">
        <div class="row"><input name="username" placeholder="{tr(lang,'username')}" required></div>
        <div class="row" style="margin-top:10px;"><input name="password" type="password" placeholder="{tr(lang,'password')}" required></div>
        <input type="hidden" name="next" value="{next_url}">
        <input type="hidden" name="ts" id="tsLogin" value="">
        <div class="row" style="margin-top:12px;">
          <button class="btn" type="submit">{tr(lang,'login')}</button>
          <a class="pill" href="{url_for('register')}">{tr(lang,'register')}</a>
        </div>
      </form>
    </div>
    <script>document.getElementById('tsLogin').value = String(Date.now());</script>
    """
    return render_page(tr(lang, "login"), body)


@APP.post("/login")
@rate_limit("login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    next_url = request.form.get("next") or url_for("home")
    lang = get_user_settings(None)["lang"]

    ts = request.form.get("ts", "")
    try:
        if ts:
            delta = time.time() - (int(ts) / 1000)
            if delta < 1.2:
                return render_page(tr(lang, "login"), f"<div class='card danger'><b>{tr(lang,'bot_blocked')}</b></div>")
    except Exception:
        pass

    lock_msg = lockout_check(username)
    if lock_msg:
        return render_page(tr(lang, "login"), f"<div class='card danger'><b>{lock_msg}</b></div>")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    u = cur.fetchone()
    conn.close()

    if not u or not check_password_hash(u["password_hash"], password) or u["is_blocked"] == 1:
        lockout_fail(username)
        return render_page(tr(lang, "login"), f"<div class='card danger'><b>{tr(lang,'invalid_login')}</b></div>")

    lockout_success(username)
    session["user_id"] = u["id"]
    return redirect(next_url)


@APP.get("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("home"))


@APP.get("/register")
def register():
    allow = get_site_setting("allow_register", "1") == "1"
    s = get_user_settings(None)
    lang = s["lang"]
    if not allow:
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'register_disabled')}</b></div>")

    body = f"""
    <div class="card col-6">
      <h2 style="margin-top:0;">🆕 {tr(lang,'register')}</h2>
      <form method="post" action="{url_for('register_post')}">
        <div class="row"><input name="username" placeholder="{tr(lang,'username')}" required></div>
        <div class="row" style="margin-top:10px;"><input name="password" type="password" placeholder="{tr(lang,'password')} (min 8)" required></div>
        <div class="row" style="margin-top:10px;"><input name="password2" type="password" placeholder="{tr(lang,'password2')}" required></div>
        <div class="row" style="margin-top:10px;"><input name="invite_code" placeholder="{tr(lang,'invite_code')}" required></div>

        <div class="hiddenhp">
          <label>Website</label>
          <input name="website" value="">
        </div>

        <input type="hidden" name="ts" id="tsReg" value="">
        <div class="row" style="margin-top:12px;">
          <button class="btn" type="submit">{tr(lang,'register')}</button>
          <a class="pill" href="{url_for('login')}">{tr(lang,'login')}</a>
        </div>
      </form>
      <div class="muted small" style="margin-top:10px;">Invite nötig (Admin kann Codes ändern).</div>
    </div>
    <script>document.getElementById('tsReg').value = String(Date.now());</script>
    """
    return render_page(tr(lang, "register"), body)


@APP.post("/register")
@rate_limit("register")
def register_post():
    allow = get_site_setting("allow_register", "1") == "1"
    s = get_user_settings(None)
    lang = s["lang"]
    if not allow:
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'register_disabled')}</b></div>")

    if (request.form.get("website") or "").strip():
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'bot_blocked')}</b></div>")

    ts = request.form.get("ts", "")
    try:
        if ts:
            delta = time.time() - (int(ts) / 1000)
            if delta < 1.5:
                return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'bot_blocked')}</b></div>")
    except Exception:
        pass

    username = (request.form.get("username") or "").strip()
    pw1 = (request.form.get("password") or "").strip()
    pw2 = (request.form.get("password2") or "").strip()
    invite = (request.form.get("invite_code") or "").strip()

    codes_raw = get_site_setting("invite_codes", "i3mad2026")
    valid_codes = {c.strip() for c in codes_raw.split(",") if c.strip()}
    if invite not in valid_codes:
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'invite_wrong')}</b></div>")

    if not valid_username(username):
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'bad_username')}</b></div>")
    if pw1 != pw2:
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'password_mismatch')}</b></div>")
    if len(pw1) < 8:
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'password_too_short')}</b></div>")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
    if cur.fetchone() is not None:
        conn.close()
        return render_page(tr(lang, "register"), f"<div class='card danger'><b>{tr(lang,'username_taken')}</b></div>")

    cur.execute(
        "INSERT INTO users(username,password_hash,role,is_blocked,created_at) VALUES(?,?,?,?,?)",
        (username, generate_password_hash(pw1), "user", 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    uid = cur.lastrowid
    for k, v in DEFAULT_USER_SETTINGS.items():
        cur.execute("INSERT INTO user_settings(user_id,k,v) VALUES(?,?,?)", (uid, k, v))
    conn.commit()
    conn.close()

    session["user_id"] = uid
    return redirect(url_for("home"))


@APP.get("/")
def home():
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s["lang"]
    city, country, method = s["city"], s["country"], s["method"]

    err = None
    timings = {}
    tz_name = ""
    next_name = None
    next_iso = None
    try:
        timings, tz_name, next_name, next_iso = compute_next_prayer(city, country, method)
    except Exception as e:
        err = str(e)

    vod = verse_of_day(lang)
    done_today = set()
    streak = 0
    if uid:
        done_today = done_today_set(uid)
        streak = compute_streak(uid)

    if err or not next_iso:
        return render_page(tr(lang, "home"),
                           f"<div class='card'><b>{tr(lang,'error_prayer_load')}:</b> {err}<br><a class='pill' href='{url_for('settings')}'>⚙ {tr(lang,'settings')}</a></div>")

    pills = "".join([f"<span class='badge'>{p}: <b>{timings.get(p,'-')}</b></span>" for p in PRAYERS])
    done_count = len(done_today)
    progress_bar = int((done_count / 5) * 100) if uid else 0

    if uid:
        mark_html = "".join([f"""
          <form method="post" action="{url_for('track_done')}" style="margin:0;">
            <input type="hidden" name="prayer" value="{p}">
            <button class="btn" type="submit">{'✅' if p in done_today else '⬜'} {p}</button>
          </form>
        """ for p in PRAYERS])
    else:
        mark_html = f"<div class='muted'>{tr(lang,'auth_required')} <a class='pill' href='{url_for('login')}'>{tr(lang,'login')}</a></div>"

    body = f"""
    <div class="grid">
      <div class="card col-8">
        <div class="row" style="justify-content:space-between;">
          <div>
            <div class="muted">{tr(lang,'next_prayer')}</div>
            <div class="big"><span class="ok">{next_name}</span></div>
            <div class="muted">{city}, {country} • {tr(lang,'timezone')}: <b>{tz_name}</b></div>
          </div>
          <div class="badge" style="font-size:18px;">
            {tr(lang,'remaining')}: <b id="countdown">...</b>
          </div>
        </div>
        <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">{pills}</div>
        <div style="margin-top:14px;" class="row">
          <a class="pill" href="{url_for('prayer_times')}">{tr(lang,'prayer_times')}</a>
          <a class="pill" href="{url_for('settings')}">⚙ {tr(lang,'settings')}</a>
        </div>
      </div>

      <div class="card col-4">
        <div class="muted">{tr(lang,'progress_today')}</div>
        <div class="big">{(str(done_count)+'/5') if uid else '—'}</div>
        <div class="muted small">{tr(lang,'today')}: {date.today().isoformat()}</div>
        <div style="margin-top:10px; border:1px solid var(--border); border-radius:12px; overflow:hidden;">
          <div style="height:10px; width:{progress_bar}%; background: color-mix(in srgb, var(--ok) 65%, transparent);"></div>
        </div>
        <div style="margin-top:12px;">
          <div class="muted small">{tr(lang,'streak')}</div>
          <div class="big">{streak if uid else '—'}</div>
          <div class="muted small">{tr(lang,'streak_desc')}</div>
        </div>
      </div>

      <div class="card col-6">
        <h3 style="margin-top:0;">{tr(lang,'mark_done')}</h3>
        <div class="row">{mark_html}</div>
      </div>

      <div class="card col-6">
        <h3 style="margin-top:0;">{tr(lang,'verse_of_day')}</h3>
        <div class="muted small">{vod.get('ref','-')}</div>
        <div style="margin-top:10px; font-size:18px;">{vod.get('ar','')}</div>
        <div class="muted" style="margin-top:10px;">{vod.get('tr','')}</div>
      </div>
    </div>

    <script>
      const target = new Date("{next_iso}");
      function tick() {{
        const now = new Date();
        let diff = Math.floor((target - now) / 1000);
        if (diff < 0) diff = 0;
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        const s = diff % 60;
        const txt = (h>0 ? h + "h " : "") + String(m).padStart(2,"0") + "m " + String(s).padStart(2,"0") + "s";
        const el = document.getElementById("countdown");
        if (el) el.textContent = txt;
      }}
      tick(); setInterval(tick, 1000);
    </script>
    """
    return render_page(tr(lang, "home"), body)


@APP.get("/gebetszeiten")
def prayer_times():
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s["lang"]
    city, country, method = s["city"], s["country"], s["method"]
    err = None
    timings = None
    tz = None
    try:
        timings, tz = fetch_prayer_times(city, country, method)
    except Exception as e:
        err = str(e)

    if err or not timings:
        return render_page(tr(lang, "prayer_times"),
                           f"<div class='card'><b>{tr(lang,'error_prayer_load')}:</b> {err} <br><a class='pill' href='{url_for('settings')}'>⚙ {tr(lang,'settings')}</a></div>")

    rows = "".join([f"<tr><td>{p}</td><td><b>{timings.get(p,'-')}</b></td></tr>" for p in PRAYERS])
    body = f"""
    <div class="card">
      <h2 style="margin-top:0;">{tr(lang,'prayer_times')}</h2>
      <div class="muted">{city}, {country} • {tr(lang,'timezone')}: <b>{tz}</b> • {tr(lang,'method')}: <b>{method}</b></div>
      <div style="margin-top:10px;">
        <table>
          <tr><th>Prayer</th><th>{tr(lang,'time')}</th></tr>
          {rows}
        </table>
      </div>
    </div>
    """
    return render_page(tr(lang, "prayer_times"), body)


@APP.post("/tracker/done")
@login_required
@rate_limit("track_done")
def track_done():
    u = current_user()
    uid = u["id"]
    s = get_user_settings(uid)
    prayer = (request.form.get("prayer") or "").strip()
    if prayer not in set(PRAYERS):
        return redirect(url_for("home"))

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO prayers(user_id, day, city, country, prayer, done_at) VALUES(?,?,?,?,?,?)",
        (uid, today_str(), s["city"], s["country"], prayer, datetime.now().strftime("%H:%M:%S")),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("home"))


@APP.get("/tracker")
@login_required
def tracker():
    u = current_user()
    uid = u["id"]
    s = get_user_settings(uid)
    lang = s["lang"]

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT prayer FROM prayers WHERE user_id=? AND day=? GROUP BY prayer", (uid, today_str()))
    done_today = {row["prayer"] for row in cur.fetchall()}
    cur.execute("SELECT day, prayer, city, done_at FROM prayers WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))
    last = cur.fetchall()
    conn.close()

    streak = compute_streak(uid)
    buttons_html = "".join([f"""
        <form method="post" action="{url_for('track_done')}" style="display:inline-block; margin:6px;">
          <input type="hidden" name="prayer" value="{p}">
          <button class="btn" type="submit">{'✅' if p in done_today else '⬜'} {p}</button>
        </form>
    """ for p in PRAYERS])

    last_rows = "".join([f"<tr><td>{r['day']}</td><td><b>{r['prayer']}</b></td><td>{r['city']}</td><td>{r['done_at']}</td></tr>" for r in last]) \
        or f"<tr><td colspan='4' class='muted'>{tr(lang,'no_entries')}</td></tr>"

    body = f"""
    <div class="grid">
      <div class="card col-4">
        <div class="muted">{tr(lang,'streak')}</div>
        <div class="big">{streak}</div>
        <div class="muted small">{tr(lang,'streak_desc')}</div>
      </div>

      <div class="card col-8">
        <h2 style="margin-top:0;">{tr(lang,'tracker')} · <span class="muted">{today_str()}</span></h2>
        <div class="muted">{tr(lang,'mark_done')}:</div>
        <div style="margin-top:6px;">{buttons_html}</div>
      </div>

      <div class="card col-12">
        <h3 style="margin-top:0;">{tr(lang,'last_entries')}</h3>
        <table>
          <tr><th>{tr(lang,'date')}</th><th>Prayer</th><th>{tr(lang,'city')}</th><th>{tr(lang,'time')}</th></tr>
          {last_rows}
        </table>
      </div>
    </div>
    """
    return render_page(tr(lang, "tracker"), body)


@APP.get("/quran")
def quran():
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s["lang"]

    err = None
    surahs = []
    try:
        r = requests.get("https://api.alquran.cloud/v1/surah", timeout=15)
        r.raise_for_status()
        surahs = r.json()["data"]
    except Exception as e:
        err = str(e)

    if err:
        return render_page(tr(lang, "quran"), f"<div class='card danger'><b>{tr(lang,'error')}:</b> {err}</div>")

    items = "".join([
        f"<li style='margin:6px 0;'><a class='pill' href='{url_for('quran_surah', number=su['number'])}'>"
        f"{tr(lang,'surah')} {su['number']}: {su['englishName']} ({su['name']})</a></li>"
        for su in surahs
    ])

    body = f"""
    <div class="card">
      <h2 style="margin-top:0;">{tr(lang,'quran')} – {tr(lang,'surahs')}</h2>
      <div class="row">
        <a class="pill" href="{url_for('quran_search')}">🔎 {tr(lang,'search')}</a>
        {"<a class='pill' href='"+url_for('favorites')+"'>⭐ "+tr(lang,'favorites')+"</a>" if uid else ""}
      </div>
      <ol style="padding-left:18px; margin-top:12px;">{items}</ol>
    </div>
    """
    return render_page(tr(lang, "quran"), body)


@APP.get("/quran/<int:number>")
def quran_surah(number: int):
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s["lang"]

    edition = request.args.get("edition", "quran-uthmani")
    url = f"https://api.alquran.cloud/v1/surah/{number}/{edition}"

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        surah = r.json()["data"]
    except Exception as e:
        return render_page("Surah", f"<div class='card danger'><b>{tr(lang,'error')}:</b> {e}</div>")

    favs = get_favorites_set(uid) if uid else set()
    ayahs_html = ""
    for a in surah["ayahs"][:60]:
        verse_key = f"{number}:{a['numberInSurah']}"
        star = "⭐" if verse_key in favs else "☆"
        if uid:
            star_btn = f"""
              <form method="post" action="{url_for('favorite_toggle')}" style="margin:0;">
                <input type="hidden" name="verse_key" value="{verse_key}">
                <input type="hidden" name="return_to" value="{url_for('quran_surah', number=number, edition=edition)}">
                <button class="btn" type="submit">{star}</button>
              </form>
            """
        else:
            star_btn = f"<a class='pill' href='{url_for('login')}'>{tr(lang,'login')}</a>"

        ayahs_html += f"""
        <div class="card" style="margin:10px 0; padding:12px;">
          <div class="row" style="justify-content:space-between;">
            <div><b>{a['numberInSurah']}.</b></div>
            {star_btn}
          </div>
          <div style="margin-top:8px; font-size:18px;">{a['text']}</div>
        </div>
        """

    tr_edition = "en.sahih" if lang != "de" else "de.aburida"

    body = f"""
    <div class="card">
      <h2 style="margin-top:0;">{tr(lang,'surah')} {surah['number']}: {surah['englishName']} ({surah['name']})</h2>
      <div class="row">
        <a class="pill" href="{url_for('quran_surah', number=number, edition='quran-uthmani')}">{tr(lang,'arabic')}</a>
        <a class="pill" href="{url_for('quran_surah', number=number, edition=tr_edition)}">{tr(lang,'translation')}</a>
        <a class="pill" href="{url_for('quran_search')}">🔎 {tr(lang,'search')}</a>
        <a class="pill" href="{url_for('quran')}">← {tr(lang,'back')}</a>
      </div>
      <div class="muted" style="margin-top:10px;">{tr(lang,'showing_first_60')}</div>
    </div>
    {ayahs_html}
    """
    return render_page("Surah", body)


@APP.get("/quran/suche")
def quran_search():
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s["lang"]
    q = (request.args.get("q") or "").strip()
    api_lang = (request.args.get("api_lang") or "en").strip().lower()

    results_html = ""
    err = None

    if q:
        try:
            url = "https://alquran-api.pages.dev/api/quran/search"
            params = {"q": q, "lang": api_lang}
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            candidates = data.get("results") or data.get("data") or data.get("verses") or []
            if isinstance(candidates, dict):
                candidates = candidates.get("results") or []

            favs = get_favorites_set(uid) if uid else set()
            if not candidates:
                results_html = f"<div class='card muted'>{tr(lang,'no_results')}</div>"
            else:
                blocks = []
                for item in candidates[:25]:
                    verse_key = item.get("verseKey") or item.get("verse_key") or item.get("key") or item.get("reference") or "?:?"
                    text = item.get("text") or item.get("translation") or item.get("content") or ""
                    text = re.sub(r"</?(?!em\b)[a-zA-Z][^>]*>", "", text or "")

                    star = "⭐" if verse_key in favs else "☆"
                    if uid:
                        star_btn = f"""
                        <form method="post" action="{url_for('favorite_toggle')}" style="margin:0;">
                          <input type="hidden" name="verse_key" value="{verse_key}">
                          <input type="hidden" name="return_to" value="{url_for('quran_search', q=q, api_lang=api_lang)}">
                          <button class="btn" type="submit">{star}</button>
                        </form>
                        """
                    else:
                        star_btn = f"<a class='pill' href='{url_for('login')}'>{tr(lang,'login')}</a>"

                    blocks.append(f"""
                      <div class="card">
                        <div class="row" style="justify-content:space-between;">
                          <b>{verse_key}</b>
                          {star_btn}
                        </div>
                        <div style="margin-top:10px;">{text}</div>
                      </div>
                    """)
                results_html = "".join(blocks)

        except Exception as e:
            err = str(e)

    body = f"""
    <div class="card">
      <h2 style="margin-top:0;">{tr(lang,'quran_search')}</h2>
      <form method="get" class="row">
        <input name="q" value="{q}" placeholder="{tr(lang,'search_placeholder')}">
        <select name="api_lang">
          <option value="de" {"selected" if api_lang=="de" else ""}>DE</option>
          <option value="en" {"selected" if api_lang=="en" else ""}>EN</option>
          <option value="ar" {"selected" if api_lang=="ar" else ""}>AR</option>
        </select>
        <button class="btn" type="submit">{tr(lang,'search')}</button>
      </form>
    </div>
    {f"<div class='card danger'><b>{tr(lang,'error')}:</b> {err}</div>" if err else ""}
    {results_html}
    """
    return render_page(tr(lang, "quran_search"), body)


@APP.post("/favorit/toggle")
@login_required
@rate_limit("favorite")
def favorite_toggle():
    u = current_user()
    uid = u["id"]
    verse_key = (request.form.get("verse_key") or "").strip()
    return_to = request.form.get("return_to") or url_for("favorites")
    if verse_key and verse_key != "?:?":
        toggle_favorite(uid, verse_key)
    return redirect(return_to)


@APP.get("/favoriten")
@login_required
def favorites():
    u = current_user()
    uid = u["id"]
    s = get_user_settings(uid)
    lang = s["lang"]

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT verse_key, added_at FROM favorites WHERE user_id=? ORDER BY id DESC", (uid,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return render_page(tr(lang, "favorites"), f"<div class='card'><h2>⭐ {tr(lang,'favorites')}</h2><p class='muted'>{tr(lang,'no_favorites')}</p></div>")

    items = ""
    for r in rows:
        vk = r["verse_key"]
        items += f"""
        <div class="card">
          <div class="row" style="justify-content:space-between;">
            <b>{vk}</b>
            <form method="post" action="{url_for('favorite_toggle')}" style="margin:0;">
              <input type="hidden" name="verse_key" value="{vk}">
              <input type="hidden" name="return_to" value="{url_for('favorites')}">
              <button class="btn" type="submit">⭐ {tr(lang,'remove')}</button>
            </form>
          </div>
          <div class="muted small" style="margin-top:8px;">{tr(lang,'added')}: {r["added_at"]}</div>
        </div>
        """
    return render_page(tr(lang, "favorites"), f"<div class='card'><h2 style='margin-top:0;'>⭐ {tr(lang,'favorites')}</h2><p class='muted'>{tr(lang,'favorites_tip')}</p></div>{items}")


@APP.get("/settings")
def settings():
    u = current_user()
    uid = u["id"] if u else None
    s = get_user_settings(uid)
    lang = s["lang"]

    lang_options = "".join([f"<option value='{code}' {'selected' if code==s['lang'] else ''}>{name}</option>" for code, name in LANGS])
    theme_options = "".join([
        f"<option value='auto' {'selected' if s['theme']=='auto' else ''}>{tr(lang,'auto')}</option>",
        f"<option value='dark' {'selected' if s['theme']=='dark' else ''}>{tr(lang,'dark')}</option>",
        f"<option value='light' {'selected' if s['theme']=='light' else ''}>{tr(lang,'light')}</option>",
    ])

    body = f"""
    <div class="card">
      <h2 style="margin-top:0;">⚙ {tr(lang,'settings')}</h2>
      <form method="post" action="{url_for('settings_save')}">
        <div class="row">
          <label class="muted">{tr(lang,'language')}</label>
          <select name="lang">{lang_options}</select>
        </div>

        <div style="margin-top:10px;">
          <div class="muted">“Sprachen: BS DE EN TR AR FR IT ES … / City Suche tippen”</div>
          <input id="citySearch" placeholder="{tr(lang,'pick_city')}…" autocomplete="off" style="width:100%; margin-top:10px;">
          <div id="cityResults" class="listbox" style="display:none;"></div>
          <input type="hidden" name="city" id="cityValue" value="{s['city']}">
          <input type="hidden" name="country" id="countryValue" value="{s['country']}">
          <div class="muted small" style="margin-top:10px;">{tr(lang,'city')}: <b id="pickedCity">{s['city']}</b> • {tr(lang,'country')}: <b id="pickedCountry">{s['country']}</b></div>
        </div>

        <div class="row" style="margin-top:12px;">
          <div>
            <div class="muted small">{tr(lang,'method')}</div>
            <select name="method">
              <option value="3" {"selected" if s['method']=="3" else ""}>3 - Muslim World League</option>
              <option value="5" {"selected" if s['method']=="5" else ""}>5 - Egypt</option>
              <option value="13" {"selected" if s['method']=="13" else ""}>13 - Kuwait</option>
              <option value="2" {"selected" if s['method']=="2" else ""}>2 - ISNA</option>
              <option value="4" {"selected" if s['method']=="4" else ""}>4 - Umm al-Qura</option>
            </select>
          </div>

          <div>
            <div class="muted small">{tr(lang,'theme')}</div>
            <select name="theme">{theme_options}</select>
          </div>
        </div>

        <div style="margin-top:14px;" class="row">
          <button class="btn" type="submit">✅ {tr(lang,'save')}</button>
          <a class="pill" href="{url_for('home')}">← {tr(lang,'home')}</a>
        </div>
      </form>
    </div>

    <script>
      const input = document.getElementById("citySearch");
      const box = document.getElementById("cityResults");
      const cityValue = document.getElementById("cityValue");
      const countryValue = document.getElementById("countryValue");
      const pickedCity = document.getElementById("pickedCity");
      const pickedCountry = document.getElementById("pickedCountry");
      let timer = null;

      function hideBox() { box.style.display="none"; box.innerHTML=""; }
      function showResults(items) {
        if (!items || items.length===0) { hideBox(); return; }
        box.innerHTML="";
        items.forEach(it=>{
          const b=document.createElement("button");
          b.type="button";
          b.textContent=it.label;
          b.addEventListener("click", ()=>{
            cityValue.value=it.city;
            countryValue.value=it.country;
            pickedCity.textContent=it.city;
            pickedCountry.textContent=it.country;
            input.value=it.city + ", " + it.country;
            hideBox();
          });
          box.appendChild(b);
        });
        box.style.display="block";
      }
      async function doSearch(q){
        const res=await fetch("/api/city_search?q="+encodeURIComponent(q));
        const data=await res.json();
        showResults(data.results||[]);
      }
      input.addEventListener("input", ()=>{
        const q=input.value.trim();
        if (timer) clearTimeout(timer);
        if (q.length<2){ hideBox(); return; }
        timer=setTimeout(()=>doSearch(q), 350);
      });
      document.addEventListener("click",(e)=>{
        if (!box.contains(e.target) && e.target!==input) hideBox();
      });
    </script>
    """
    return render_page(tr(lang, "settings"), body)


@APP.post("/settings/save")
def settings_save():
    u = current_user()
    uid = u["id"] if u else None

    lang = (request.form.get("lang") or DEFAULT_USER_SETTINGS["lang"]).strip().lower()
    if lang not in T:
        lang = "en"

    city = (request.form.get("city") or "").strip()
    country = (request.form.get("country") or "").strip()
    method = (request.form.get("method") or DEFAULT_USER_SETTINGS["method"]).strip()
    theme = (request.form.get("theme") or DEFAULT_USER_SETTINGS["theme"]).strip()

    if not city or not country:
        s_old = get_user_settings(uid)
        city = city or s_old["city"]
        country = country or s_old["country"]

    set_user_setting(uid, "lang", lang)
    set_user_setting(uid, "city", city)
    set_user_setting(uid, "country", country)
    set_user_setting(uid, "method", method)
    set_user_setting(uid, "theme", theme if theme in ("auto", "dark", "light") else "auto")

    return redirect(url_for("settings"))


@APP.get("/api/city_search")
@rate_limit("city_search")
def api_city_search():
    q = (request.args.get("q") or "").strip()
    try:
        return jsonify({"results": search_city_nominatim(q)})
    except Exception:
        return jsonify({"results": []})


@APP.get("/admin")
@admin_required
def admin_panel():
    u = current_user()
    uid = u["id"]
    s = get_user_settings(uid)
    lang = s["lang"]

    allow_register = get_site_setting("allow_register", "1")
    invite_codes = get_site_setting("invite_codes", "i3mad2026")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, is_blocked, created_at FROM users ORDER BY created_at ASC")
    users = cur.fetchall()
    conn.close()

    rows = ""
    for x in users:
        is_me = (x["username"] == ADMIN_USERNAME)
        status = tr(lang, "blocked") if x["is_blocked"] == 1 else tr(lang, "active")
        actions = []
        if not is_me:
            if x["is_blocked"] == 1:
                actions.append(f"<a class='pill' href='{url_for('admin_unblock', user_id=x['id'])}'>{tr(lang,'unblock')}</a>")
            else:
                actions.append(f"<a class='pill' href='{url_for('admin_block', user_id=x['id'])}'>{tr(lang,'block')}</a>")
            if x["role"] == "admin":
                actions.append(f"<a class='pill' href='{url_for('admin_make_user', user_id=x['id'])}'>{tr(lang,'make_user')}</a>")
            else:
                actions.append(f"<a class='pill' href='{url_for('admin_make_admin', user_id=x['id'])}'>{tr(lang,'make_admin')}</a>")

        rows += f"""
        <tr>
          <td><b>{x['username']}</b></td>
          <td>{x['role']}</td>
          <td>{status}</td>
          <td class="small">{x['created_at']}</td>
          <td>{" ".join(actions) if actions else "<span class='muted small'>—</span>"}</td>
        </tr>
        """

    body = f"""
    <div class="card">
      <h2 style="margin-top:0;">🛡 {tr(lang,'admin_panel')}</h2>

      <div class="card">
        <h3 style="margin-top:0;">⚙ {tr(lang,'site_settings')}</h3>
        <form method="post" action="{url_for('admin_site_settings')}">
          <div class="row">
            <label class="muted small">{tr(lang,'allow_register')}</label>
            <select name="allow_register">
              <option value="1" {"selected" if allow_register=="1" else ""}>{tr(lang,'yes')}</option>
              <option value="0" {"selected" if allow_register=="0" else ""}>{tr(lang,'no')}</option>
            </select>
          </div>

          <div class="row" style="margin-top:10px;">
            <label class="muted small">{tr(lang,'invite_codes')}</label>
            <input name="invite_codes" value="{invite_codes}" placeholder="code1, code2, code3" style="width:100%;">
          </div>

          <div class="row" style="margin-top:12px;">
            <button class="btn" type="submit">{tr(lang,'update')}</button>
          </div>
          <div class="muted small" style="margin-top:10px;">Beispiel: <b>i3mad2026, bosna, vip2026</b></div>
        </form>
      </div>

      <div class="card">
        <h3 style="margin-top:0;">🔐 {tr(lang,'change_admin_pass')}</h3>
        <form method="post" action="{url_for('admin_change_password')}">
          <div class="row">
            <input name="new_password" type="password" placeholder="{tr(lang,'new_password')}" required>
            <button class="btn" type="submit">{tr(lang,'update')}</button>
          </div>
          <div class="muted small" style="margin-top:10px;">Bitte ändere sofort das Startpasswort <b>123456</b>.</div>
        </form>
      </div>

      <h3>👤 {tr(lang,'users')}</h3>
      <table>
        <tr>
          <th>{tr(lang,'username')}</th>
          <th>{tr(lang,'role')}</th>
          <th>{tr(lang,'status')}</th>
          <th>{tr(lang,'created')}</th>
          <th>Actions</th>
        </tr>
        {rows}
      </table>
    </div>
    """
    return render_page(tr(lang, "admin_panel"), body)


@APP.post("/admin/site")
@admin_required
def admin_site_settings():
    allow = request.form.get("allow_register", "1").strip()
    inv = (request.form.get("invite_codes") or "i3mad2026").strip()
    set_site_setting("allow_register", "1" if allow == "1" else "0")
    set_site_setting("invite_codes", inv)
    return redirect(url_for("admin_panel"))


@APP.post("/admin/change_password")
@admin_required
def admin_change_password():
    new_pw = (request.form.get("new_password") or "").strip()
    u = current_user()
    uid = u["id"]
    lang = get_user_settings(uid)["lang"]
    if len(new_pw) < 8:
        return render_page(tr(lang, "admin_panel"), f"<div class='card danger'><b>{tr(lang,'password_too_short')}</b></div>")

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash=? WHERE username=?", (generate_password_hash(new_pw), ADMIN_USERNAME))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@APP.get("/admin/block/<int:user_id>")
@admin_required
def admin_block(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked=1 WHERE id=? AND username<>?", (user_id, ADMIN_USERNAME))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@APP.get("/admin/unblock/<int:user_id>")
@admin_required
def admin_unblock(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_blocked=0 WHERE id=? AND username<>?", (user_id, ADMIN_USERNAME))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@APP.get("/admin/make_admin/<int:user_id>")
@admin_required
def admin_make_admin(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET role='admin' WHERE id=? AND username<>?", (user_id, ADMIN_USERNAME))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


@APP.get("/admin/make_user/<int:user_id>")
@admin_required
def admin_make_user(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET role='user' WHERE id=? AND username<>?", (user_id, ADMIN_USERNAME))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_panel"))


# Init DB also for gunicorn import
init_db()

if __name__ == "__main__":
    APP.run(debug=True)
