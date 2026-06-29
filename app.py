"""Self-hosted home lab dashboard.

A single FastAPI app that serves the JSON API and the static frontend, stores
links and users in SQLite, checks service status server-side on a background
loop, and serves over HTTPS using a persistent self-signed certificate.

Auth: accounts live in SQLite with pbkdf2-hashed passwords. On first run (no
users yet) the frontend runs a one-time "create admin" setup. After that, every
request requires a logged-in session; admins can manage other users.
"""

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urljoin

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------- #
# Config (read once at startup)
# --------------------------------------------------------------------------- #
DB_PATH = os.environ.get("DASH_DB_PATH", "/data/dashboard.db")
INTERVAL = int(os.environ.get("DASH_INTERVAL", "30"))
CHECK_TIMEOUT = float(os.environ.get("DASH_CHECK_TIMEOUT", "4"))
PORT = int(os.environ.get("DASH_PORT", "8443"))
CERT_PATH = os.environ.get("DASH_TLS_CERT", "/data/cert.pem")
KEY_PATH = os.environ.get("DASH_TLS_KEY", "/data/key.pem")
TLS_HOSTS = [h.strip() for h in os.environ.get("DASH_TLS_HOSTS", "").split(",") if h.strip()]

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_CONCURRENT_CHECKS = 20
MIN_PASSWORD_LEN = 8
PBKDF2_ITERATIONS = 200_000


def _read_version() -> str:
    v = os.environ.get("DASH_VERSION", "").strip()
    if v:
        return v
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    except Exception:
        return "0.0.0"


APP_VERSION = _read_version()
# Update checks are off until you point them at a repo (or a custom URL).
UPDATE_REPO = os.environ.get("DASH_UPDATE_REPO", "").strip()
UPDATE_URL = os.environ.get("DASH_UPDATE_URL", "").strip() or (
    f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest" if UPDATE_REPO else ""
)
UPDATE_COMMAND = os.environ.get("DASH_UPDATE_COMMAND", "docker compose pull && docker compose up -d")
UPDATE_INTERVAL = int(os.environ.get("DASH_UPDATE_INTERVAL", "86400"))

# --------------------------------------------------------------------------- #
# Database (stdlib sqlite3; single connection guarded by a lock)
# --------------------------------------------------------------------------- #
_db_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def init_db() -> None:
    global _conn
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _db_lock:
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                host        TEXT NOT NULL,
                port        INTEGER NOT NULL,
                tags        TEXT NOT NULL DEFAULT '',
                check_type  TEXT NOT NULL DEFAULT 'tcp',
                scheme      TEXT NOT NULL DEFAULT 'http',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL
            )
            """
        )
        # sessions schema changed (now references a user); migrate older DBs.
        cols = [r[1] for r in _conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if cols and "user_id" not in cols:
            _conn.execute("DROP TABLE sessions")
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favicons (
                link_id      INTEGER PRIMARY KEY,
                content_type TEXT NOT NULL,
                data         BLOB NOT NULL,
                fetched_at   TEXT NOT NULL
            )
            """
        )
        _conn.commit()


_LINK_COLS = ("name", "description", "host", "port", "tags", "check_type", "scheme")


def db_all_links() -> list[dict]:
    with _db_lock:
        rows = _conn.execute("SELECT * FROM links ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def db_get_link(link_id: int) -> Optional[dict]:
    with _db_lock:
        row = _conn.execute("SELECT * FROM links WHERE id=?", (link_id,)).fetchone()
    return dict(row) if row else None


def db_create_link(data: dict) -> dict:
    ts = now_iso()
    vals = tuple(data[c] for c in _LINK_COLS)
    with _db_lock:
        cur = _conn.execute(
            """INSERT INTO links (name, description, host, port, tags, check_type, scheme,
                                  created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*vals, ts, ts),
        )
        _conn.commit()
        row = _conn.execute("SELECT * FROM links WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def db_update_link(link_id: int, data: dict) -> Optional[dict]:
    ts = now_iso()
    vals = tuple(data[c] for c in _LINK_COLS)
    with _db_lock:
        cur = _conn.execute(
            """UPDATE links SET name=?, description=?, host=?, port=?, tags=?, check_type=?,
                                scheme=?, updated_at=?
               WHERE id=?""",
            (*vals, ts, link_id),
        )
        _conn.commit()
        if cur.rowcount == 0:
            return None
        row = _conn.execute("SELECT * FROM links WHERE id=?", (link_id,)).fetchone()
    return dict(row)


def db_delete_link(link_id: int) -> bool:
    with _db_lock:
        cur = _conn.execute("DELETE FROM links WHERE id=?", (link_id,))
        _conn.commit()
    return cur.rowcount > 0


# ----- users & sessions ----------------------------------------------------- #
def db_user_count() -> int:
    with _db_lock:
        return _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def db_admin_count() -> int:
    with _db_lock:
        return _conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]


def db_get_user(uid: int) -> Optional[dict]:
    with _db_lock:
        row = _conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def db_get_user_by_name(username: str) -> Optional[dict]:
    with _db_lock:
        row = _conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    return dict(row) if row else None


def db_all_users() -> list[dict]:
    with _db_lock:
        rows = _conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [dict(r) for r in rows]


def db_create_user(username: str, password_hash: str, is_admin: bool) -> dict:
    with _db_lock:
        cur = _conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, 1 if is_admin else 0, now_iso()),
        )
        _conn.commit()
        row = _conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def db_set_password(uid: int, password_hash: str) -> bool:
    with _db_lock:
        cur = _conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))
        _conn.commit()
    return cur.rowcount > 0


def db_delete_user(uid: int) -> bool:
    with _db_lock:
        _conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        cur = _conn.execute("DELETE FROM users WHERE id=?", (uid,))
        _conn.commit()
    return cur.rowcount > 0


def db_add_session(token: str, user_id: int) -> None:
    with _db_lock:
        _conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, now_iso()),
        )
        _conn.commit()


def db_session_user(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    with _db_lock:
        row = _conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=?",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def db_del_session(token: str) -> None:
    with _db_lock:
        _conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        _conn.commit()


# ----- favicons ------------------------------------------------------------- #
def db_set_favicon(link_id: int, content_type: str, data: bytes, ts: str) -> None:
    with _db_lock:
        _conn.execute(
            "INSERT OR REPLACE INTO favicons (link_id, content_type, data, fetched_at) VALUES (?, ?, ?, ?)",
            (link_id, content_type, sqlite3.Binary(data), ts),
        )
        _conn.commit()


def db_get_favicon(link_id: int):
    with _db_lock:
        row = _conn.execute("SELECT content_type, data FROM favicons WHERE link_id=?", (link_id,)).fetchone()
    return (row["content_type"], bytes(row["data"])) if row else None


def db_delete_favicon(link_id: int) -> None:
    with _db_lock:
        _conn.execute("DELETE FROM favicons WHERE link_id=?", (link_id,))
        _conn.commit()


def db_favicon_meta() -> dict:
    with _db_lock:
        rows = _conn.execute("SELECT link_id, fetched_at FROM favicons").fetchall()
    return {r["link_id"]: r["fetched_at"] for r in rows}


# --------------------------------------------------------------------------- #
# Password hashing (stdlib pbkdf2)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


# A throwaway hash so a missing username costs the same time as a real one.
_DUMMY_HASH = hash_password("dash-timing-equalizer")


# --------------------------------------------------------------------------- #
# TLS — generate & persist a self-signed certificate if none is supplied
# --------------------------------------------------------------------------- #
def ensure_cert(cert_path: str, key_path: str, extra_hosts=()) -> None:
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    parent = os.path.dirname(cert_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alt_names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    host = socket.gethostname()
    if host and host != "localhost":
        alt_names.append(x509.DNSName(host))
    for h in extra_hosts:
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt_names.append(x509.DNSName(h))

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dash")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    os.chmod(key_path, 0o600)
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


# --------------------------------------------------------------------------- #
# Status checking (runs entirely inside the asyncio event loop)
# --------------------------------------------------------------------------- #
status_cache: dict[int, dict] = {}
http_client: Optional[httpx.AsyncClient] = None
_check_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

UNKNOWN = {"status": "unknown", "latency_ms": None, "last_checked": None, "resolved": None}


async def _check_tcp(host: str, port: int) -> tuple[bool, Optional[float]]:
    start = time.perf_counter()
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=CHECK_TIMEOUT
        )
        return True, (time.perf_counter() - start) * 1000
    except Exception:
        return False, None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def _check_http(scheme: str, host: str, port: int) -> tuple[bool, Optional[float]]:
    start = time.perf_counter()
    try:
        # Any HTTP response (incl. 401/403/404) means the service is up.
        await http_client.get(f"{scheme}://{host}:{port}", timeout=CHECK_TIMEOUT)
        return True, (time.perf_counter() - start) * 1000
    except Exception:
        return False, None


async def _resolve_counterpart(host: str, prev: Optional[str]) -> Optional[str]:
    """Discover the DNS counterpart of a host: if it's an IP, reverse-resolve to a
    name (PTR); if it's a name, forward-resolve to an IP. Returns the discovered
    value, or the previous one on failure (avoids flicker)."""
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    try:
        if is_ip:
            name, _, _ = await asyncio.wait_for(
                asyncio.to_thread(socket.gethostbyaddr, host), timeout=CHECK_TIMEOUT
            )
            return name
        infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None), timeout=CHECK_TIMEOUT
        )
        addrs = [info[4][0] for info in infos]
        ipv4 = next((a for a in addrs if ":" not in a), None)
        return ipv4 or (addrs[0] if addrs else prev)
    except Exception:
        return prev


async def check_link(link: dict) -> dict:
    link_id = link["id"]
    prev = status_cache.get(link_id, UNKNOWN)
    status_cache[link_id] = {**prev, "status": "checking"}
    async with _check_semaphore:
        if link["check_type"] == "http":
            ok, latency = await _check_http(link["scheme"], link["host"], link["port"])
        else:
            ok, latency = await _check_tcp(link["host"], link["port"])
        resolved = await _resolve_counterpart(link["host"], prev.get("resolved"))
    status_cache[link_id] = {
        "status": "online" if ok else "offline",
        "latency_ms": round(latency) if latency is not None else None,
        "last_checked": now_iso(),
        "resolved": resolved,
    }
    if link_id not in favicon_tried:
        asyncio.create_task(ensure_favicon(link))
    return status_cache[link_id]


async def check_all_links() -> None:
    links = await asyncio.to_thread(db_all_links)
    if links:
        await asyncio.gather(*(check_link(l) for l in links), return_exceptions=True)


async def _checker_loop() -> None:
    while True:
        try:
            await check_all_links()
        except Exception:
            pass
        await asyncio.sleep(INTERVAL)


# --------------------------------------------------------------------------- #
# Favicons (best-effort: fetch each service's own icon; offline-safe on a LAN)
# --------------------------------------------------------------------------- #
favicon_meta: dict[int, str] = {}   # link_id -> fetched_at (presence + cache-bust token)
favicon_tried: set[int] = set()     # link_ids attempted this run (don't retry every cycle)
FAVICON_MAX_BYTES = 512 * 1024
_FAVICON_TYPES = {
    "image/x-icon", "image/vnd.microsoft.icon", "image/png", "image/gif",
    "image/jpeg", "image/svg+xml", "image/webp", "image/bmp",
}


def _looks_like_image(content_type: str, data: bytes) -> bool:
    if (content_type or "").split(";")[0].strip().lower() in _FAVICON_TYPES:
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:2] == b"\xff\xd8":                       # JPEG
        return True
    if data[:4] == b"\x00\x00\x01\x00":               # ICO
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if b"<svg" in data[:300].lower():
        return True
    return False


async def _fetch_favicon(link: dict):
    base = f"{link['scheme']}://{link['host']}:{link['port']}"
    urls: list[str] = []
    try:  # parse the homepage for <link rel="...icon..." href="...">
        resp = await http_client.get(base + "/", timeout=CHECK_TIMEOUT)
        for tag in re.findall(r"<link\b[^>]*>", resp.text[:200000], re.I):
            if re.search(r'rel\s*=\s*["\']?[^"\'>]*icon', tag, re.I):
                href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.I)
                if href:
                    urls.append(urljoin(base + "/", href.group(1)))
    except Exception:
        pass
    urls.append(base + "/favicon.ico")
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = await http_client.get(url, timeout=CHECK_TIMEOUT)
            data = resp.content
            if resp.status_code == 200 and 0 < len(data) <= FAVICON_MAX_BYTES and \
                    _looks_like_image(resp.headers.get("content-type", ""), data):
                ct = resp.headers.get("content-type", "").split(";")[0].strip() or "image/x-icon"
                return ct, data
        except Exception:
            pass
    return None


async def ensure_favicon(link: dict) -> None:
    lid = link["id"]
    if lid in favicon_tried:
        return
    favicon_tried.add(lid)
    try:
        got = await _fetch_favicon(link)
    except Exception:
        got = None
    if got:
        ct, data = got
        ts = now_iso()
        await asyncio.to_thread(db_set_favicon, lid, ct, data, ts)
        favicon_meta[lid] = ts


# --------------------------------------------------------------------------- #
# Update checking (best-effort GitHub release check; fail-silent when offline)
# --------------------------------------------------------------------------- #
update_state = {
    "current": APP_VERSION,
    "latest": None,
    "available": False,
    "configured": bool(UPDATE_URL),
    "ok": None,            # last check succeeded? (None = not yet checked)
    "error": None,
    "checked_at": None,
    "release_url": None,
    "command": UPDATE_COMMAND,
}


def _parse_semver(s: Optional[str]) -> Optional[tuple]:
    if not s:
        return None
    parts = (s.strip().lstrip("vV").split(".") + ["0", "0", "0"])[:3]
    out = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _is_newer(latest: Optional[str], current: Optional[str]) -> bool:
    a, b = _parse_semver(latest), _parse_semver(current)
    return bool(a and b and a > b)


async def check_update() -> dict:
    if not UPDATE_URL:
        update_state.update(configured=False, ok=None)
        return update_state
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                UPDATE_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "dash-dashboard"},
            )
        resp.raise_for_status()
        data = resp.json()
        latest = (data.get("tag_name") or data.get("name") or "").strip()
        update_state.update(
            latest=latest or None,
            release_url=data.get("html_url"),
            available=_is_newer(latest, APP_VERSION),
            ok=True,
            error=None,
            checked_at=now_iso(),
        )
    except Exception as exc:
        update_state.update(ok=False, error=str(exc)[:200], checked_at=now_iso())
    return update_state


async def _update_loop() -> None:
    await asyncio.sleep(10)  # settle after startup
    while True:
        if UPDATE_URL:
            try:
                await check_update()
            except Exception:
                pass
        await asyncio.sleep(max(300, UPDATE_INTERVAL))


# --------------------------------------------------------------------------- #
# App lifespan
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    init_db()
    http_client = httpx.AsyncClient(verify=False, follow_redirects=True)
    for link in db_all_links():
        status_cache.setdefault(link["id"], dict(UNKNOWN))
    favicon_meta.update(db_favicon_meta())
    tasks = [asyncio.create_task(_checker_loop()), asyncio.create_task(_update_loop())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        await http_client.aclose()
        with _db_lock:
            if _conn is not None:
                _conn.close()


app = FastAPI(title="Dash", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class LinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    tags: str = Field(default="", max_length=500)
    check_type: Literal["tcp", "http"] = "tcp"
    scheme: Literal["http", "https"] = "http"

    @field_validator("name", "host")
    @classmethod
    def _strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("description", "tags")
    @classmethod
    def _strip_optional(cls, v: str) -> str:
        return v.strip()


class ImportIn(BaseModel):
    links: list[LinkIn] = Field(default_factory=list, max_length=2000)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class NewAccount(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=256)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def _strip_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class PasswordChange(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=256)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _public_user(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"])}


async def _current_user(request: Request) -> Optional[dict]:
    return await asyncio.to_thread(db_session_user, request.cookies.get("session"))


async def require_auth(request: Request) -> dict:
    user = await _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(request: Request) -> dict:
    user = await require_auth(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "session", token, httponly=True, samesite="lax", secure=True,
        max_age=60 * 60 * 24 * 30, path="/",
    )


async def _start_session(response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    await asyncio.to_thread(db_add_session, token, user_id)
    _set_session_cookie(response, token)


@app.get("/api/me")
async def api_me(request: Request):
    if await asyncio.to_thread(db_user_count) == 0:
        return {"setup_required": True, "authenticated": False, "user": None, "version": APP_VERSION}
    user = await _current_user(request)
    return {
        "setup_required": False,
        "authenticated": user is not None,
        "user": _public_user(user) if user else None,
        "version": APP_VERSION,
    }


@app.post("/api/setup", status_code=201)
async def api_setup(body: NewAccount, response: Response):
    if await asyncio.to_thread(db_user_count) > 0:
        raise HTTPException(status_code=409, detail="Setup already completed")
    user = await asyncio.to_thread(db_create_user, body.username, hash_password(body.password), True)
    await _start_session(response, user["id"])
    return {"ok": True, "user": _public_user(user)}


@app.post("/api/login")
async def api_login(body: Credentials, response: Response):
    user = await asyncio.to_thread(db_get_user_by_name, body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        if not user:
            verify_password(body.password, _DUMMY_HASH)  # equalize timing
        raise HTTPException(status_code=401, detail="Invalid username or password")
    await _start_session(response, user["id"])
    return {"ok": True, "user": _public_user(user)}


@app.post("/api/logout")
async def api_logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        await asyncio.to_thread(db_del_session, token)
    response.delete_cookie("session", path="/")
    return {"ok": True}


# ----- user management (admin) --------------------------------------------- #
@app.get("/api/users")
async def api_list_users(admin: dict = Depends(require_admin)):
    return [_public_user(u) | {"created_at": u["created_at"]} for u in await asyncio.to_thread(db_all_users)]


@app.post("/api/users", status_code=201)
async def api_create_user(body: NewAccount, admin: dict = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(db_create_user, body.username, hash_password(body.password), body.is_admin)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username already exists")
    return _public_user(user)


@app.delete("/api/users/{uid}")
async def api_delete_user(uid: int, admin: dict = Depends(require_admin)):
    if uid == admin["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    target = await asyncio.to_thread(db_get_user, uid)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["is_admin"] and await asyncio.to_thread(db_admin_count) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last admin")
    await asyncio.to_thread(db_delete_user, uid)
    return {"ok": True}


@app.post("/api/users/{uid}/password")
async def api_set_password(uid: int, body: PasswordChange, user: dict = Depends(require_auth)):
    # Admins may reset anyone's password; a normal user may change only their own.
    if not user["is_admin"] and uid != user["id"]:
        raise HTTPException(status_code=403, detail="Not allowed")
    if not await asyncio.to_thread(db_get_user, uid):
        raise HTTPException(status_code=404, detail="User not found")
    await asyncio.to_thread(db_set_password, uid, hash_password(body.password))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Links API (all require a logged-in session)
# --------------------------------------------------------------------------- #
def serialize(link: dict) -> dict:
    st = status_cache.get(link["id"], UNKNOWN)
    return {
        **link,
        "status": st.get("status", "unknown"),
        "latency_ms": st.get("latency_ms"),
        "last_checked": st.get("last_checked"),
        "resolved": st.get("resolved"),
        "favicon": favicon_meta.get(link["id"]),
    }


@app.get("/api/links", dependencies=[Depends(require_auth)])
async def api_links():
    links = await asyncio.to_thread(db_all_links)
    return [serialize(l) for l in links]


@app.post("/api/links", dependencies=[Depends(require_auth)], status_code=201)
async def api_create_link(body: LinkIn):
    link = await asyncio.to_thread(db_create_link, body.model_dump())
    status_cache[link["id"]] = dict(UNKNOWN)
    asyncio.create_task(check_link(link))
    return serialize(link)


@app.post("/api/links/import", dependencies=[Depends(require_auth)])
async def api_import_links(body: ImportIn):
    existing = await asyncio.to_thread(db_all_links)
    seen = {(l["name"].lower(), l["host"].lower(), int(l["port"])) for l in existing}
    added = skipped = 0
    for item in body.links:
        key = (item.name.lower(), item.host.lower(), item.port)
        if key in seen:
            skipped += 1
            continue
        link = await asyncio.to_thread(db_create_link, item.model_dump())
        status_cache[link["id"]] = dict(UNKNOWN)
        asyncio.create_task(check_link(link))
        seen.add(key)
        added += 1
    return {"added": added, "skipped": skipped}


@app.put("/api/links/{link_id}", dependencies=[Depends(require_auth)])
async def api_update_link(link_id: int, body: LinkIn):
    link = await asyncio.to_thread(db_update_link, link_id, body.model_dump())
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    # Host/port/scheme may have changed — drop the cached favicon so it re-fetches.
    favicon_meta.pop(link_id, None)
    favicon_tried.discard(link_id)
    await asyncio.to_thread(db_delete_favicon, link_id)
    asyncio.create_task(check_link(link))
    return serialize(link)


@app.delete("/api/links/{link_id}", dependencies=[Depends(require_auth)])
async def api_delete_link(link_id: int):
    if not await asyncio.to_thread(db_delete_link, link_id):
        raise HTTPException(status_code=404, detail="Link not found")
    status_cache.pop(link_id, None)
    favicon_meta.pop(link_id, None)
    favicon_tried.discard(link_id)
    await asyncio.to_thread(db_delete_favicon, link_id)
    return {"ok": True}


@app.get("/api/links/{link_id}/favicon", dependencies=[Depends(require_auth)])
async def api_link_favicon(link_id: int):
    row = await asyncio.to_thread(db_get_favicon, link_id)
    if not row:
        raise HTTPException(status_code=404, detail="No favicon")
    content_type, data = row
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/links/{link_id}/check", dependencies=[Depends(require_auth)])
async def api_check_link(link_id: int):
    link = await asyncio.to_thread(db_get_link, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    await check_link(link)
    return serialize(link)


@app.post("/api/check-all", dependencies=[Depends(require_auth)])
async def api_check_all():
    await check_all_links()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Update status
# --------------------------------------------------------------------------- #
@app.get("/api/update", dependencies=[Depends(require_auth)])
async def api_update():
    return dict(update_state)


@app.post("/api/update/check", dependencies=[Depends(require_auth)])
async def api_update_check():
    return await check_update()


# --------------------------------------------------------------------------- #
# Static frontend
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    ensure_cert(CERT_PATH, KEY_PATH, TLS_HOSTS)
    uvicorn.run(app, host="0.0.0.0", port=PORT, ssl_certfile=CERT_PATH, ssl_keyfile=KEY_PATH)
