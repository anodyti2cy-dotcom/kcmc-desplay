import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import ssl
import time
from contextlib import contextmanager
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("KANISA_DB_PATH", ROOT / "kanisa.sqlite3"))
HOST = os.environ.get("KANISA_HOST", "127.0.0.1")
PORT = int(os.environ.get("KANISA_PORT", "5500"))
PUBLIC_ORIGIN = os.environ.get("KANISA_PUBLIC_ORIGIN", "").rstrip("/")
COOKIE_SECURE = os.environ.get("KANISA_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
SETUP_TOKEN = os.environ.get("KANISA_SETUP_TOKEN", "")
SETUP_TOKEN_REQUIRED = HOST not in ("127.0.0.1", "localhost", "::1") or bool(PUBLIC_ORIGIN) or COOKIE_SECURE
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 600_000
MAX_REQUEST_BYTES = 2_000_000
MAX_AVATAR_BYTES = 1_000_000
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_FAILURES = 8
SESSION_COOKIE = "tag_session"
LANGUAGES = {"sw", "en"}
THEMES = {"light", "dark", "blue"}
STATIC_EXTENSIONS = {
    ".html", ".js", ".css", ".xml", ".json", ".png", ".jpg", ".jpeg",
    ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf",
}
AVATAR_TYPES = {
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with database() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL UNIQUE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                avatar_mime TEXT NOT NULL,
                avatar BLOB NOT NULL,
                language TEXT NOT NULL DEFAULT 'sw',
                theme TEXT NOT NULL DEFAULT 'light',
                created_at INTEGER NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash BLOB PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                address TEXT NOT NULL,
                attempted_at INTEGER NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at)")
        db.execute("CREATE INDEX IF NOT EXISTS login_attempts_time ON login_attempts(address, attempted_at)")


def password_digest(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)


def parse_avatar(value, required=False):
    if not value:
        if required:
            raise ApiError(400, "Picha ya wasifu inahitajika.")
        return None

    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/]+={0,2})", value)
    if not match:
        raise ApiError(400, "Tumia picha ya JPG, PNG au WebP.")
    mime, encoded = match.groups()
    try:
        image = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ApiError(400, "Faili la picha halijasomeka.") from None
    if not image or len(image) > MAX_AVATAR_BYTES or not AVATAR_TYPES[mime](image):
        raise ApiError(400, "Picha lazima iwe JPG, PNG au WebP chini ya MB 1.")
    return mime, image


def account_exists(db):
    return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def profile_data(user):
    encoded = base64.b64encode(user["avatar"]).decode("ascii")
    return {
        "username": user["username"],
        "avatar": "data:" + user["avatar_mime"] + ";base64," + encoded,
        "language": user["language"],
        "theme": user["theme"],
    }


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "TAGKCMC/1.0"

    def log_message(self, fmt, *args):
        super().log_message(fmt, *args)

    def send_json(self, status, payload, cookie=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, error):
        self.send_json(error.status, {"error": error.message})

    def read_json(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "Ombi hili linahitaji JSON.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Urefu wa ombi si sahihi.") from None
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ApiError(413, "Ombi ni tupu au limezidi ukubwa unaoruhusiwa.")
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "Taarifa za ombi si JSON sahihi.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "Muundo wa ombi si sahihi.")
        return data

    def check_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            raise ApiError(403, "Ombi limekataliwa.")
        expected = PUBLIC_ORIGIN
        if not expected:
            scheme = "https" if isinstance(self.connection, ssl.SSLSocket) else "http"
            expected = scheme + "://" + self.headers.get("Host", "")
        if origin.rstrip("/") != expected:
            raise ApiError(403, "Chanzo cha ombi hakiruhusiwi.")

    def session_user(self, db):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        if not morsel:
            return None
        token_hash = hashlib.sha256(morsel.value.encode("ascii", "ignore")).digest()
        now = int(time.time())
        session = db.execute(
            "SELECT user_id FROM sessions WHERE token_hash = ? AND expires_at > ?",
            (token_hash, now),
        ).fetchone()
        if not session:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            return None
        return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    def issue_session(self, db, user_id):
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + SESSION_SECONDS
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        db.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode("ascii")).digest(), user_id, expires),
        )
        secure = COOKIE_SECURE or isinstance(self.connection, ssl.SSLSocket)
        cookie = (
            SESSION_COOKIE + "=" + token + "; Path=/; HttpOnly; SameSite=Strict; "
            "Max-Age=" + str(SESSION_SECONDS)
        )
        if secure:
            cookie += "; Secure"
        return cookie

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/auth/status":
            try:
                with database() as db:
                    user = self.session_user(db)
                    if user:
                        self.send_json(200, {"setup_required": False, "authenticated": True, "profile": profile_data(user)})
                    else:
                        self.send_json(200, {
                            "setup_required": not account_exists(db),
                            "setup_token_required": SETUP_TOKEN_REQUIRED,
                            "authenticated": False,
                        })
            except sqlite3.Error:
                self.log_error("Database error while checking authentication")
                self.send_json(500, {"error": "Imeshindikana kuangalia hali ya akaunti."})
            return
        page_path = unquote(parsed.path).lower()
        if page_path in ("/", "/index.html", "/login.html"):
            try:
                with database() as db:
                    authenticated = self.session_user(db) is not None
            except sqlite3.Error:
                self.log_error("Database error while checking page access")
                self.send_json(500, {"error": "Imeshindikana kuangalia ruhusa ya ukurasa."})
                return
            if page_path == "/login.html" and authenticated:
                self.redirect("/index.html")
                return
            if page_path != "/login.html" and not authenticated:
                self.redirect("/login.html")
                return
            if page_path == "/":
                self.serve_static("/index.html")
                return
        self.serve_static(parsed.path)

    def redirect(self, path):
        self.send_response(303)
        self.send_header("Location", path)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self):
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_json(404, {"error": "Njia haikupatikana."})
            return
        try:
            self.check_origin()
            data = self.read_json()
            if parsed.path == "/api/auth/setup":
                self.setup_account(data)
            elif parsed.path == "/api/auth/login":
                self.login(data)
            elif parsed.path == "/api/auth/logout":
                self.logout()
            elif parsed.path == "/api/profile":
                self.update_profile(data)
            else:
                self.send_json(404, {"error": "Njia haikupatikana."})
        except ApiError as error:
            self.send_error_json(error)
        except sqlite3.Error:
            self.log_error("Database error while processing authentication request")
            self.send_json(500, {"error": "Imeshindikana kuhifadhi taarifa. Jaribu tena."})

    def setup_account(self, data):
        username = str(data.get("username", "")).strip()
        password = data.get("password")
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", username):
            raise ApiError(400, "Jina la mtumiaji liwe na herufi 3–32: A-Z, namba, nukta, _ au -.")
        if not isinstance(password, str) or len(password) < 10 or len(password) > 256:
            raise ApiError(400, "Nenosiri liwe na angalau herufi 10.")
        avatar = parse_avatar(data.get("avatar"), required=True)
        with database() as db:
            if account_exists(db):
                raise ApiError(409, "Akaunti tayari imeanzishwa. Ingia kwa jina na nenosiri lako.")
        if SETUP_TOKEN_REQUIRED:
            supplied_token = data.get("setup_token")
            if not isinstance(supplied_token, str) or not hmac.compare_digest(supplied_token, SETUP_TOKEN):
                raise ApiError(403, "Msimbo wa usanidi si sahihi.")
        salt = secrets.token_bytes(16)
        digest = password_digest(password, salt)
        now = int(time.time())
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            if account_exists(db):
                raise ApiError(409, "Akaunti tayari imeanzishwa. Ingia kwa jina na nenosiri lako.")
            db.execute(
                """INSERT INTO users
                   (id, username, password_salt, password_hash, avatar_mime, avatar, created_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (username, salt, digest, avatar[0], avatar[1], now),
            )
            cookie = self.issue_session(db, 1)
            user = db.execute("SELECT * FROM users WHERE id = 1").fetchone()
        self.send_json(201, {"ok": True, "profile": profile_data(user)}, cookie)

    def login(self, data):
        username = str(data.get("username", "")).strip()
        password = data.get("password")
        if not isinstance(password, str) or len(password) > 256:
            raise ApiError(400, "Jina la mtumiaji au nenosiri si sahihi.")
        address = self.client_address[0]
        now = int(time.time())
        invalid_credentials = False
        with database() as db:
            db.execute("DELETE FROM login_attempts WHERE attempted_at <= ?", (now - LOGIN_WINDOW_SECONDS,))
            failures = db.execute(
                "SELECT COUNT(*) AS count FROM login_attempts WHERE address = ?",
                (address,),
            ).fetchone()["count"]
            if failures >= MAX_LOGIN_FAILURES:
                raise ApiError(429, "Majaribio mengi ya kuingia. Subiri dakika 15 kabla ya kujaribu tena.")
            user = db.execute("SELECT * FROM users WHERE id = 1").fetchone()
            valid = bool(user and hmac.compare_digest(
                password_digest(password, user["password_salt"]),
                user["password_hash"],
            ) and hmac.compare_digest(username.casefold(), user["username"].casefold()))
            if not valid:
                db.execute("INSERT INTO login_attempts(address, attempted_at) VALUES (?, ?)", (address, now))
                invalid_credentials = True
            else:
                db.execute("DELETE FROM login_attempts WHERE address = ?", (address,))
                cookie = self.issue_session(db, user["id"])
        if invalid_credentials:
            raise ApiError(401, "Jina la mtumiaji au nenosiri si sahihi.")
        self.send_json(200, {"ok": True, "profile": profile_data(user)}, cookie)

    def logout(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            cookie = SimpleCookie()
        morsel = cookie.get(SESSION_COOKIE)
        if morsel:
            token_hash = hashlib.sha256(morsel.value.encode("ascii", "ignore")).digest()
            with database() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        self.send_json(
            200,
            {"ok": True},
            SESSION_COOKIE + "=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0; "
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            + ("; Secure" if COOKIE_SECURE or isinstance(self.connection, ssl.SSLSocket) else ""),
        )

    def update_profile(self, data):
        language = data.get("language")
        theme = data.get("theme")
        if language not in LANGUAGES or theme not in THEMES:
            raise ApiError(400, "Lugha au mandhari haijaruhusiwa.")
        avatar = parse_avatar(data.get("avatar"))
        with database() as db:
            user = self.session_user(db)
            if not user:
                raise ApiError(401, "Ingia tena ili kuendelea.")
            if avatar:
                db.execute(
                    "UPDATE users SET language = ?, theme = ?, avatar_mime = ?, avatar = ? WHERE id = ?",
                    (language, theme, avatar[0], avatar[1], user["id"]),
                )
            else:
                db.execute(
                    "UPDATE users SET language = ?, theme = ? WHERE id = ?",
                    (language, theme, user["id"]),
                )
            updated = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        self.send_json(200, {"ok": True, "profile": profile_data(updated)})

    def serve_static(self, url_path):
        decoded = unquote(url_path)
        if decoded in ("", "/"):
            decoded = "/index.html"
        target = (ROOT / decoded.lstrip("/\\")).resolve()
        try:
            inside_root = os.path.commonpath((str(ROOT), str(target))) == str(ROOT)
        except ValueError:
            inside_root = False
        if not inside_root or target.suffix.lower() not in STATIC_EXTENSIONS or not target.is_file():
            self.send_json(404, {"error": "Faili halikupatikana."})
            return
        try:
            body = target.read_bytes()
        except OSError:
            self.send_json(500, {"error": "Imeshindikana kusoma faili."})
            return
        mime, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", (mime or "application/octet-stream") + ("; charset=utf-8" if mime and mime.startswith("text/") or mime in ("application/javascript", "application/json", "application/xml") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if target.suffix.lower() == ".html":
            self.send_header("Cache-Control", "no-store")
            if target.name.lower() in ("index.html", "login.html"):
                self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run():
    use_tls = bool(os.environ.get("KANISA_TLS_CERT") and os.environ.get("KANISA_TLS_KEY"))
    if HOST not in ("127.0.0.1", "localhost", "::1") and not use_tls:
        raise SystemExit("Kwa usalama, KANISA_HOST isiyo localhost inahitaji KANISA_TLS_CERT na KANISA_TLS_KEY.")
    if SETUP_TOKEN_REQUIRED and len(SETUP_TOKEN) < 32:
        raise SystemExit("KANISA_SETUP_TOKEN inahitajika kwa seva ya mtandao na lazima iwe na angalau herufi 32.")
    init_db()
    httpd = Server((HOST, PORT), RequestHandler)
    if use_tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(os.environ["KANISA_TLS_CERT"], os.environ["KANISA_TLS_KEY"])
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    print("Mfumo wa TAG KCMC unasikiliza kwenye " + ("https" if use_tls else "http") + "://" + HOST + ":" + str(PORT))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nSeva imesimamishwa.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run()
