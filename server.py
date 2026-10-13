"""CDB Bäumlis web portal: static site, Discord OAuth and application API.

Uses only Python's standard library. Configure secrets through environment
variables (Render) or a local .env file; never put secrets in website assets.
"""
from __future__ import annotations

import hashlib
import hmac
import http.cookies
import json
import logging
import os
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SITE_ROOT = ROOT / "public"
LOG = logging.getLogger("cdb.website")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")


def load_local_env() -> None:
    """Load a simple .env file without overriding Render/system variables."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        os.environ.setdefault(key.strip(), value)


load_local_env()
PORT = int(os.getenv("PORT", "3000"))
WEBSITE_URL = os.getenv("WEBSITE_URL", "").strip().rstrip("/")
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "").strip() or (f"{WEBSITE_URL}/auth/callback" if WEBSITE_URL else "")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()
ACCEPTED_ROLE_ID = os.getenv("RULES_ACCEPTED_ROLE_ID", "").strip()
APPLICATION_CHANNEL_ID = os.getenv("APPLICATION_CHANNEL_ID", "").strip()
COOKIE_SECURE = WEBSITE_URL.startswith("https://")

STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "bewerbung.html": "text/html; charset=utf-8",
    "spieler.html": "text/html; charset=utf-8",
    "quests.html": "text/html; charset=utf-8",
    "builds.html": "text/html; charset=utf-8",
    "events.html": "text/html; charset=utf-8",
    "regeln.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "admin.js": "text/javascript; charset=utf-8",
    "application.js": "text/javascript; charset=utf-8",
}
CATEGORIES = {"Mitglied", "Builder", "Coder", "Supporter", "Anwerber", "Kassenwart"}
SESSIONS: dict[str, dict] = {}
SUBMITTED_AT: dict[str, float] = {}
SESSION_TTL = 7 * 24 * 60 * 60


def discord_request(url: str, *, method: str = "GET", headers: dict | None = None, body: bytes | None = None):
    req = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except (URLError, TimeoutError) as exc:
        LOG.warning("Discord API nicht erreichbar (%s).", type(exc).__name__)
        return 0, b""


def response_json(status: int, data: dict) -> tuple[int, bytes]:
    return status, json.dumps(data, ensure_ascii=False).encode("utf-8")


def parse_discord_body(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "CDBPortal/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        # Never write OAuth query parameters (temporary code/state) to logs.
        path = urlsplit(self.path).path
        LOG.info("%s %s", self.command, path)

    def cookies(self) -> http.cookies.SimpleCookie:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            pass
        return jar

    def cookie_header(self, name: str, value: str, max_age: int) -> str:
        morsel = http.cookies.Morsel()
        morsel.set(name, value, value)
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["max-age"] = str(max_age)
        if COOKIE_SECURE:
            morsel["secure"] = True
        return morsel.OutputString()

    def send_bytes(self, status: int, body: bytes, content_type: str, *, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        for key, value in (headers or {}).items():
            if isinstance(value, list):
                for item in value:
                    self.send_header(key, item)
            else:
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json_response(self, status: int, data: dict, *, headers: dict | None = None) -> None:
        self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", headers=headers)

    def redirect(self, location: str, cookies: list[str] | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        for item in cookies or []:
            self.send_header("Set-Cookie", item)
        self.end_headers()

    def request_session(self):
        jar = self.cookies()
        morsel = jar.get("cdb_session")
        session_id = morsel.value if morsel else ""
        session = SESSIONS.get(session_id)
        if not session or session["expires"] < time.time():
            SESSIONS.pop(session_id, None)
            return "", None
        return session_id, session

    def body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 16_000:
            raise ValueError("Ungültige Anfragegröße.")
        value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("Ungültige Anfrage.")
        return value

    def csrf_valid(self, session: dict) -> bool:
        return hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session.get("csrf", ""))

    def rules_accepted(self, session: dict) -> bool:
        if not GUILD_ID or not ACCEPTED_ROLE_ID or not session.get("access_token"):
            return False
        url = f"https://discord.com/api/v10/users/@me/guilds/{GUILD_ID}/member"
        status, body = discord_request(url, headers={"Authorization": f"Bearer {session['access_token']}"})
        if status != 200:
            LOG.warning("Discord-Rollenprüfung fehlgeschlagen (HTTP %s).", status)
            return False
        return ACCEPTED_ROLE_ID in parse_discord_body(body).get("roles", [])

    def oauth_start(self) -> None:
        if not (WEBSITE_URL and CLIENT_ID and CLIENT_SECRET and REDIRECT_URI):
            self.json_response(503, {"error": "Discord-Anmeldung ist noch nicht konfiguriert."})
            return
        state = secrets.token_urlsafe(32)
        params = urlencode({"client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI,
                            "scope": "identify guilds.members.read", "state": state})
        self.redirect("https://discord.com/oauth2/authorize?" + params,
                      [self.cookie_header("cdb_oauth_state", state, 600)])

    def oauth_callback(self, query: dict) -> None:
        jar = self.cookies()
        state_morsel = jar.get("cdb_oauth_state")
        saved_state = state_morsel.value if state_morsel else ""
        query_state = (query.get("state") or [""])[0]
        provider_error = (query.get("error") or [""])[0]
        clear_state = self.cookie_header("cdb_oauth_state", "", 0)

        def failed(reason: str):
            LOG.warning("[OAuth] %s", reason)
            self.redirect("/bewerbung.html?login=failed#formular", [clear_state])

        if provider_error:
            failed(f"Discord hat die Anmeldung abgebrochen ({provider_error}).")
            return
        if not saved_state or not query_state or not hmac.compare_digest(saved_state, query_state):
            failed(f"State-Prüfung fehlgeschlagen (Cookie vorhanden: {bool(saved_state)}, Rückgabe vorhanden: {bool(query_state)}).")
            return
        code = (query.get("code") or [""])[0]
        if not code:
            failed("Discord hat keinen Autorisierungscode zurückgegeben.")
            return
        body = urlencode({"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                          "grant_type": "authorization_code", "code": code,
                          "redirect_uri": REDIRECT_URI}).encode("utf-8")
        status, token_body = discord_request("https://discord.com/api/v10/oauth2/token", method="POST",
                                             headers={"Content-Type": "application/x-www-form-urlencoded"}, body=body)
        if status != 200:
            token_error = parse_discord_body(token_body)
            reason = ": ".join(filter(None, [token_error.get("error"), token_error.get("error_description")])) or "keine Zusatzinformation"
            LOG.error("[OAuth] Token-Austausch fehlgeschlagen (HTTP %s; %s).", status, reason)
            self.redirect("/bewerbung.html?login=failed#formular", [clear_state])
            return
        token_data = parse_discord_body(token_body)
        access_token = token_data.get("access_token")
        if not access_token:
            failed("Discord-Token fehlt in der Antwort.")
            return
        user_status, user_body = discord_request("https://discord.com/api/v10/users/@me",
                                                 headers={"Authorization": f"Bearer {access_token}"})
        if user_status != 200:
            LOG.error("[OAuth] Profilabruf fehlgeschlagen (HTTP %s).", user_status)
            self.redirect("/bewerbung.html?login=failed#formular", [clear_state])
            return
        user = parse_discord_body(user_body)
        if not user.get("id"):
            failed("Discord hat kein gültiges Profil zurückgegeben.")
            return
        session_id = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        username = user.get("username", "Discord-Mitglied")
        global_name = user.get("global_name") or username
        ttl = min(int(token_data.get("expires_in") or SESSION_TTL), SESSION_TTL)
        SESSIONS[session_id] = {
            "user": {"id": user["id"], "name": global_name, "globalName": global_name,
                     "username": username, "avatar": user.get("avatar")},
            "access_token": access_token, "csrf": csrf, "expires": time.time() + ttl,
        }
        self.redirect("/bewerbung.html#formular", [self.cookie_header("cdb_session", session_id, ttl), clear_state])

    def application_payload(self, session: dict, data: dict) -> dict:
        def clean(key: str, limit: int) -> str:
            value = data.get(key, "")
            return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""

        minecraft = clean("minecraft", 16)
        age_text = clean("age", 3)
        category = clean("category", 40)
        experience = clean("experience", 1000)
        motivation = clean("motivation", 1000)
        availability = clean("availability", 300)
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", minecraft):
            raise ValueError("Bitte prüfe deinen Minecraft-Namen.")
        try:
            age = int(age_text)
        except ValueError as exc:
            raise ValueError("Bitte gib ein Alter zwischen 10 und 99 an.") from exc
        if not 10 <= age <= 99:
            raise ValueError("Bitte gib ein Alter zwischen 10 und 99 an.")
        if category not in CATEGORIES or len(experience) < 10 or len(motivation) < 10 or len(availability) < 3:
            raise ValueError("Bitte fülle alle Fragen vollständig aus.")
        if data.get("privacy") != "on":
            raise ValueError("Bitte bestätige die Hinweise zur Verarbeitung deiner Angaben.")
        user = session["user"]
        embed = {
            "title": f"🌱 Neue Website-Bewerbung · {category}", "color": 0x43E8EF,
            "description": f"**Discord:** <@{user['id']}> · {user['username']}\n**Minecraft:** {minecraft}\n**Alter:** {age}",
            "fields": [{"name": "Bereich", "value": category},
                       {"name": "Erfahrung & Stärken", "value": experience},
                       {"name": "Warum [CDB] Bäumlis?", "value": motivation},
                       {"name": "Aktivität / Onlinezeiten", "value": availability}],
            "footer": {"text": f"CDB Bäumlis · Discord-ID {user['id']}"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return {"embeds": [embed], "allowed_mentions": {"parse": []}}

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/auth/discord":
            self.oauth_start(); return
        if path == "/auth/callback":
            self.oauth_callback(query); return
        if path == "/api/me":
            _, session = self.request_session()
            if not session:
                self.json_response(200, {"authenticated": False}); return
            user_data = dict(session["user"])
            user_data["globalName"] = user_data.get("globalName")
            self.json_response(200, {"authenticated": True, "user": user_data,
                                     "rulesAccepted": self.rules_accepted(session), "csrf": session["csrf"]})
            return
        if path == "/health":
            self.json_response(200, {"ok": True, "service": "cdb-website"}); return
        name = "index.html" if path == "/" else path.lstrip("/")
        if "/" in name or name not in STATIC_FILES:
            self.send_bytes(404, b"Not Found", "text/plain; charset=utf-8"); return
        try:
            content = (SITE_ROOT / name).read_bytes()
        except OSError:
            self.send_bytes(404, b"Not Found", "text/plain; charset=utf-8"); return
        self.send_bytes(200, content, STATIC_FILES[name], headers={"Cache-Control": "no-cache" if name == "service-worker.js" else "public, max-age=300"})

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        session_id, session = self.request_session()
        if path == "/api/logout":
            if not session:
                self.json_response(200, {"success": True}, headers={"Set-Cookie": self.cookie_header("cdb_session", "", 0)}); return
            if not self.csrf_valid(session):
                self.json_response(403, {"error": "Sitzung abgelaufen. Bitte neu anmelden."}); return
            SESSIONS.pop(session_id, None)
            self.json_response(200, {"success": True}, headers={"Set-Cookie": self.cookie_header("cdb_session", "", 0)}); return
        if path != "/api/applications":
            self.json_response(404, {"error": "Nicht gefunden."}); return
        if not session:
            self.json_response(401, {"error": "Bitte zuerst mit Discord anmelden."}); return
        if not self.csrf_valid(session):
            self.json_response(403, {"error": "Sicherheitsprüfung fehlgeschlagen. Bitte Seite neu laden."}); return
        if not self.rules_accepted(session):
            self.json_response(403, {"error": "Bitte akzeptiere zuerst die Regeln im Discord-Bot."}); return
        now = time.time()
        if now - SUBMITTED_AT.get(session["user"]["id"], 0) < 60:
            self.json_response(429, {"error": "Bitte warte kurz, bevor du erneut absendest."}); return
        try:
            data = self.body_json()
            payload = self.application_payload(session, data)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.json_response(400, {"error": str(exc) or "Ungültige Anfrage."}); return
        if not BOT_TOKEN or not APPLICATION_CHANNEL_ID:
            self.json_response(503, {"error": "Der Bewerbungs-Kanal ist noch nicht konfiguriert."}); return
        status, _ = discord_request(f"https://discord.com/api/v10/channels/{APPLICATION_CHANNEL_ID}/messages",
                                   method="POST", headers={"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"},
                                   body=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if status not in (200, 201):
            LOG.error("Discord-Bewerbung fehlgeschlagen (HTTP %s).", status)
            self.json_response(502, {"error": "Discord konnte die Bewerbung gerade nicht annehmen."}); return
        SUBMITTED_AT[session["user"]["id"]] = now
        self.json_response(200, {"success": True})

    def do_PUT(self) -> None:
        self.json_response(405, {"error": "Methode nicht erlaubt."})

    def do_DELETE(self) -> None:
        self.json_response(405, {"error": "Methode nicht erlaubt."})


if __name__ == "__main__":
    LOG.info("CDB Website läuft auf Port %s.", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), PortalHandler).serve_forever()
