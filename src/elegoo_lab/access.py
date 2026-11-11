"""Access from other devices of the home network (phone, tablet), protected by an access code.

This PC (loopback) always gets in. Anyone else needs the code once; the browser then keeps a signed
session cookie for 30 days. The code is stored only as a salted PBKDF2 hash in config.toml.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from typing import Any

from . import config

SESSION_DAYS = 30
COOKIE = "cc2_session"
MAX_FAILS, FAIL_WINDOW_S = 5, 300
PUBLIC = ("/lab/login.html", "/lab/api/login", "/lab/vendor/", "/lab/icons/", "/lab/manifest.webmanifest",
          "/lab/sw.js", "/lab/offline.html", "/lab/tableau.webmanifest", "/lab/ca.crt", "/favicon",
          "/lab/js/i18n.js", "/lab/i18n/")   # the login page in English too


def _settings() -> dict[str, Any]:
    if config.CONFIG_FILE.exists():
        import tomllib
        return tomllib.loads(config.CONFIG_FILE.read_text()).get("acces", {})
    return {}


def _hash(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), 200_000).hex()


def ensure_code() -> str | None:
    """Create a 6-digit access code if none exists; returns it (only then) so it can be shown once."""
    if _settings().get("code_hash"):
        return None
    code = f"{secrets.randbelow(10**6):06d}"
    set_code(code)
    return code


def set_code(code: str) -> None:
    if not (code.isdigit() and 4 <= len(code) <= 12):
        raise ValueError("le code d'accès doit faire 4 à 12 chiffres")
    salt = secrets.token_hex(16)
    config.save("acces", code_hash=_hash(code, salt), salt=salt, secret=secrets.token_hex(32))  # new secret: old sessions end


def check_code(code: str) -> bool:
    s = _settings()
    return bool(s.get("code_hash")) and hmac.compare_digest(_hash(str(code), s["salt"]), s["code_hash"])


def make_session() -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    sig = hmac.new(bytes.fromhex(_settings()["secret"]), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_session(token: str | None) -> bool:
    secret = _settings().get("secret")
    if not token or not secret or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    good = hmac.new(bytes.fromhex(secret), exp.encode(), hashlib.sha256).hexdigest()
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, good)


def is_local(host: str | None) -> bool:
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # nothing is sent: picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def tailscale() -> dict[str, str] | None:
    """This PC on the user's Tailscale network (reachable from anywhere by their own devices), if it is up."""
    import shutil
    import subprocess
    if not shutil.which("tailscale"):
        return None
    try:
        r = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5)
        me = json.loads(r.stdout)["Self"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None
    ip = next((a for a in me.get("TailscaleIPs") or [] if ":" not in a), "")
    if not me.get("Online") or not ip:
        return None
    return {"ip": ip, "name": str(me.get("DNSName") or "").rstrip(".")}


class Gate:
    """ASGI middleware: outside this PC, everything but the login page needs a valid session."""

    def __init__(self, app: Any, https_port: int = 0) -> None:
        self.app = app
        self.https_port = https_port   # set: plain HTTP from the network only hands out the certificate
        self.fails: dict[str, list[float]] = {}

    def too_many(self, ip: str) -> bool:
        now = time.time()
        self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < FAIL_WINDOW_S]
        return len(self.fails[ip]) >= MAX_FAILS

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        ip = (scope.get("client") or ("", 0))[0]
        path = scope.get("path", "")
        if self.https_port and scope.get("scheme") in ("http", "ws") and not is_local(ip) and path != "/lab/ca.crt":
            host = next((v.decode() for k, v in scope.get("headers", []) if k == b"host"), lan_ip())
            host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
            return await _reply(send, 307, b"", [(b"location", f"https://{host}:{self.https_port}{path}".encode())])
        if is_local(ip) or path.startswith(PUBLIC):
            if path == "/lab/api/login" and scope.get("method") == "POST":
                return await self._login(scope, receive, send, ip)
            return await self.app(scope, receive, send)
        cookies = {}
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                for part in v.decode().split(";"):
                    if "=" in part:
                        a, b = part.strip().split("=", 1)
                        cookies[a] = b
        if valid_session(cookies.get(COOKIE)):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4401})
        if scope["type"] == "http" and scope.get("method") == "GET" and not path.startswith(("/lab/api", "/api", "/status", "/events", "/stream", "/snapshot", "/canvas", "/files", "/history")):
            return await _reply(send, 303, b"", [(b"location", b"/lab/login.html")])
        await _reply(send, 401, json.dumps({"detail": "Code d'accès requis"}).encode(), [(b"content-type", b"application/json")])

    async def _login(self, scope: dict, receive: Any, send: Any, ip: str) -> None:
        if self.too_many(ip):
            return await _reply(send, 429, json.dumps({"detail": "Trop d'essais : attends 5 minutes."}).encode(),
                                [(b"content-type", b"application/json")])
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        try:
            code = str(json.loads(body or b"{}").get("code", ""))
        except ValueError:
            code = ""
        if not check_code(code):
            self.fails.setdefault(ip, []).append(time.time())
            return await _reply(send, 403, json.dumps({"detail": "Code incorrect"}).encode(), [(b"content-type", b"application/json")])
        cookie = f"{COOKIE}={make_session()}; Max-Age={SESSION_DAYS * 86400}; Path=/; HttpOnly; SameSite=Strict"
        if scope.get("scheme") == "https":
            cookie += "; Secure"
        await _reply(send, 200, b'{"ok": true}', [(b"content-type", b"application/json"), (b"set-cookie", cookie.encode())])


async def _reply(send: Any, status: int, body: bytes, headers: list[tuple[bytes, bytes]]) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-length", str(len(body)).encode()), *headers]})
    await send({"type": "http.response.body", "body": body})
