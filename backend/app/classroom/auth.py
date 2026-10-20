"""Google OAuth token handling for Classroom (V5-parity, stdlib refresh).

V5 used ``google-auth`` and :class:`InstalledAppFlow`. V6 keeps the same
behaviour with the standard library only:

* a stored refresh token is exchanged silently for an access token;
* ``invalid_scope`` is reported as a reconnection need (not an expiry), the
  exact distinction V5 learned live;
* the interactive connect flow runs in a browser against Google's own
  authorization endpoint with a loopback redirect, then stores the refresh
  token in the local secrets directory.

The refresh token never leaves the process: it lives in
``<data>/secrets/classroom_refresh_token`` (inside the git-ignored data
directory) and is never logged, echoed or returned by an API.
"""

from __future__ import annotations

import base64
import http.server
import json
import logging
import secrets as _secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from .. import config
from .client import ClassroomApiError

log = logging.getLogger("mathchecker.classroom.auth")

# Scopes mirror V5 exactly so preserved behaviour keeps working.
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    # drive.file is the NARROWEST scope able to upload the correction report:
    # access only to files this app creates.
    "https://www.googleapis.com/auth/drive.file",
    # Reading student submissions from Drive.
    "https://www.googleapis.com/auth/drive.readonly",
    # Which account is connected (stored locally, never treated as a secret).
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

# A stored refresh token file larger than this is corrupt, not a real token.
MAX_TOKEN_BYTES = 4096


class AuthError(RuntimeError):
    """An authentication step failed. Message is safe to show a teacher."""


def _client_config() -> dict:
    path = config.classroom_oauth_client_path()
    if path is None or not path.is_file():
        raise AuthError(
            "Google OAuth client is not configured. Place the OAuth client JSON "
            "in the application's data directory under secrets/google_oauth_client.json "
            "or set MC6_GOOGLE_OAUTH_CLIENT."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthError("The Google OAuth client file is unreadable or invalid JSON.") from exc
    installed = payload.get("installed") or payload.get("web") or {}
    if not installed.get("client_id") or not installed.get("client_secret"):
        raise AuthError("The Google OAuth client file has no client_id/client_secret.")
    return installed


def client_configured() -> bool:
    try:
        _client_config()
    except AuthError:
        return False
    return True


# ------------------------------------------------------------- token storage

def _refresh_path() -> Path:
    return config.classroom_refresh_token_path()


def store_refresh_token(token: str) -> None:
    """Persist the refresh token inside the git-ignored data directory."""
    path = _refresh_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only the owner may read this file (best effort on platforms without POSIX)
    path.write_text(token.strip(), encoding="utf-8")
    try:
        # os.chmod on Windows only honours the read-only flag; harmless either way.
        import os

        os.chmod(path, 0o600)
    except OSError:
        pass


def read_refresh_token() -> str | None:
    try:
        value = _refresh_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value or len(value) > MAX_TOKEN_BYTES:
        return None
    return value or None


def clear_refresh_token() -> None:
    try:
        _refresh_path().unlink()
    except OSError:
        pass


def is_connected() -> bool:
    return read_refresh_token() is not None


# ------------------------------------------------------------- token refresh

def get_access_token(*, refresh_fn=None) -> str:
    """Return a valid access token, refreshing silently when needed.

    ``refresh_fn`` is injectable so tests never touch Google.
    """
    refresh_token = read_refresh_token()
    if not refresh_token:
        raise AuthError(
            "Google Classroom is not connected yet. Start the connection flow first."
        )
    _ = refresh_token  # readability: the fetcher owns the exchange
    if refresh_fn is None:
        refresh_fn = _refresh_access_token
    manifest = _read_granted_scopes()
    return refresh_fn(refresh_token, granted_scopes=manifest)


def _write_granted_scopes(scopes: str) -> None:
    path = _refresh_path().with_suffix(".scopes")
    try:
        path.write_text(scopes or "", encoding="utf-8")
    except OSError:
        pass


def _read_granted_scopes() -> str | None:
    try:
        value = _refresh_path().with_suffix(".scopes").read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def _refresh_access_token(refresh_token: str, *, granted_scopes: str | None = None) -> str:
    installed = _client_config()
    body = urllib.parse.urlencode({
        "client_id": installed.get("client_id", ""),
        "client_secret": installed.get("client_secret", ""),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001
            detail = ""
        if "invalid_scope" in str(detail).lower():
            # V5 distinction: invalid_scope on refresh is NOT an expiry; it
            # means the granted scope set differs from what we now request.
            raise AuthError(
                "Google Classroom must be reconnected to grant the permission "
                "that uploads correction reports to Drive (drive.file). Click "
                "Connect Google Classroom and approve the new permission."
            ) from exc
        if exc.code in (400, 401, 403):
            raise AuthError(
                "Google authorization expired or was revoked. Reconnect Google "
                "Classroom from the settings page."
            ) from exc
        raise AuthError(f"Google token refresh failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AuthError("Google could not be reached during token refresh.") from exc

    token = payload.get("access_token")
    if not token:
        raise AuthError("Google did not return an access token.")
    # Persist the scope set actually granted so later refreshes use it.
    granted = payload.get("scope") or granted_scopes
    if granted:
        _write_granted_scopes(granted)
    return token


# --------------------------------------------------------- interactive flow

class _RedirectCatcher(http.server.BaseHTTPRequestHandler):
    """Loopback redirect receiver for the installed-app OAuth flow."""

    query: dict[str, str] = {}
    received = threading.Event()

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("", "/"):
            _RedirectCatcher.query = urllib.parse.parse_qs(parsed.query)
            _RedirectCatcher.received.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Math Checker V6</h2>"
                b"<p>Google Classroom connected. You can close this tab.</p></body></html>"
            )
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):  # silence per-request logging
        return


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_connect_flow(*, open_browser: bool = True, timeout_seconds: int = 300,
                       redirect_fn=None) -> dict:
    """Run the installed-app OAuth flow and store the refresh token.

    ``redirect_fn(provider(port=url))`` is injectable so tests exchange the
    authorization URL for tokens without a browser or Google.
    """
    installed = _client_config()
    redirect_port = _free_port()
    redirect_uri = f"http://127.0.0.1:{redirect_port}"
    state = _secrets.token_urlsafe(24)
    params = {
        "client_id": installed.get("client_id", ""),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # access_type=offline yields a refresh token; prompt=consent guarantees
        # Google actually issues one on re-consent (V5 lesson).
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "false",
    }
    auth_url = f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    if redirect_fn is None:
        server = http.server.HTTPServer(("127.0.0.1", redirect_port), _RedirectCatcher)
        _RedirectCatcher.received.clear()
        _RedirectCatcher.query = {}
        if open_browser:
            webbrowser.open(auth_url)
        else:
            print(f"Open this URL to connect Google Classroom:\n{auth_url}")
        server.timeout = timeout_seconds
        if not _RedirectCatcher.received.wait(timeout=timeout_seconds):
            server.server_close()
            raise AuthError(
                "The Google Classroom authorization did not complete in time. Try again."
            )
        server.server_close()
        query = _RedirectCatcher.query
    else:
        query = redirect_fn(auth_url) or {}

    if query.get("state") != state:
        raise AuthError("The authorization response failed its state check. Try again.")
    if query.get("error"):
        raise AuthError(f"Google refused the connection: {query['error'][0]}")
    code = (query.get("code") or [None])[0]
    if not code:
        raise AuthError("Google did not return an authorization code. Try again.")

    tokens = _exchange_code(installed, code, redirect_uri)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise AuthError(
            "Google did not return a refresh token, so the connection cannot be "
            "kept. Please try again and approve ALL requested permissions."
        )
    store_refresh_token(refresh_token)
    granted_scopes = tokens.get("scope") or " ".join(SCOPES)
    if granted_scopes:
        _write_granted_scopes(granted_scopes)
    email = _account_email(tokens.get("access_token", ""))
    log.info("classroom OAuth completed; refresh token stored (email withheld from logs)")
    return {"connected": True, "email": email}


def _exchange_code(installed: dict, code: str, redirect_uri: str) -> dict:
    body = urllib.parse.urlencode({
        "client_id": installed.get("client_id", ""),
        "client_secret": installed.get("client_secret", ""),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error_description", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise AuthError(f"Google rejected the token exchange ({exc.code}). {detail[:200]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AuthError("Google could not be reached during the token exchange.") from exc


def _account_email(access_token: str) -> str | None:
    """Best-effort resolution of the connected account's email (local display only)."""
    if not access_token:
        return None
    try:
        request = urllib.request.Request(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("email") or None
    except Exception:  # noqa: BLE001 — cosmetic only
        return None


def disconnect() -> None:
    clear_refresh_token()
    try:
        _refresh_path().with_suffix(".scopes").unlink()
    except OSError:
        pass
    log.info("classroom disconnected")


def auth_state(*, connected: bool | None = None, email: str | None = None) -> dict:
    """Public auth snapshot. No token value is ever included."""
    configured = client_configured()
    if connected is None:
        connected = is_connected()
    problem = None
    if not configured:
        problem = (
            "OAuth client JSON missing — copy the Google client secret file into "
            "the data directory at secrets/google_oauth_client.json."
        )
    elif not connected:
        problem = "Not connected. Start the Connect Google Classroom flow."
    return {
        "configured": configured,
        "connected": bool(configured and connected),
        "email": email,
        "problem": problem,
    }
