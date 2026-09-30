"""Sign in to LiST: API key, Microsoft Entra (MSAL), or Shibboleth → LiST JWT.

Three explicit, single-purpose entry points do the actual work:
``sign_in_api_key``, ``sign_in_entra``, ``sign_in_shibboleth``. ``sign_in()``
is a convenience wrapper that resolves config/env and picks one of them, so
callers who don't care which method is used (and want it to stay silent when
already signed in to Entra or to the campus SP) can just call ``sign_in()``.
"""

from __future__ import annotations

import http.server
import logging
import os
import secrets
import threading
import webbrowser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlparse

from listapi._jwt import post_for_jwt
from listapi.client import Client
from listapi.config import load_list_config

logger = logging.getLogger(__name__)

MSAL_CACHE_PATH = Path.home() / ".list" / "msal_cache.bin"

# Interactive MSAL / Shibboleth open a browser and block on a localhost redirect.
# Closing the window does not cancel that wait — use a timeout, then fall back
# (device code for Entra; a hard error for Shibboleth, there is no headless mode).
_INTERACTIVE_TIMEOUT_SEC = 120

_UNSET = object()

EntraMode = Literal["device", "interactive", "auto"]
AuthMethod = Literal["api_key", "entra", "shibboleth"]


def sign_in(
    *,
    url: str | None = None,
    api_key: Any = _UNSET,
    api_version: int = 2,
    method: AuthMethod | None = None,
    entra: EntraMode | None = None,
) -> Client:
    """
    Build an authenticated :class:`Client`, picking a sign-in method automatically.

    Config: ``config/list.py`` (override directory with ``LIST_CONFIG_DIR``).
    Env: ``LIST_URL``, ``LIST_API_KEY``, ``LIST_AUTH_METHOD`` fill gaps when not
    passed explicitly.

    - If ``api_key`` is a non-empty string (arg, env, or config): ``X-API-Key``,
      then try ``POST /auth/jwt/api`` for a LiST JWT; on failure keep the key.
    - Otherwise, ``method`` (or ``LIST_AUTH_METHOD``) picks ``"entra"`` (default)
      or ``"shibboleth"``. Both are silent when you're already signed in
      (an Entra silent-token cache, or an existing campus SP session) and only
      prompt when they're not. Use :func:`sign_in_entra` / :func:`sign_in_shibboleth`
      directly if you want to force one without going through this resolver.
    """
    cfg_url: str | None = None
    cfg_key: str | None = None
    try:
        cfg = load_list_config()
        cfg_url = cfg.get("url")
        raw_key = cfg.get("api_key")
        cfg_key = None if raw_key in (None, "") else str(raw_key)
    except FileNotFoundError:
        pass

    resolved_url = url or os.environ.get("LIST_URL") or cfg_url
    if not resolved_url:
        raise ValueError(
            "LiST url is required (config/list.py url=, LIST_URL, or sign_in(url=...))"
        )
    resolved_url = str(resolved_url).rstrip("/")

    if api_key is _UNSET:
        env_key = os.environ.get("LIST_API_KEY")
        if env_key not in (None, ""):
            resolved_key: str | None = env_key
        else:
            resolved_key = cfg_key
    else:
        resolved_key = None if api_key in (None, "") else str(api_key)

    if resolved_key:
        return sign_in_api_key(resolved_url, resolved_key, api_version=api_version)

    resolved_method = _resolve_auth_method(method)
    if resolved_method == "shibboleth":
        return sign_in_shibboleth(resolved_url, api_version=api_version)
    mode = _resolve_entra_mode(entra)
    return sign_in_entra(resolved_url, api_version=api_version, entra_mode=mode)


def _resolve_auth_method(method: AuthMethod | None) -> Literal["entra", "shibboleth"]:
    if method is not None:
        if method == "api_key":
            raise ValueError(
                "method='api_key' has no url; call sign_in_api_key(url, key) directly"
            )
        return method
    env = (os.environ.get("LIST_AUTH_METHOD") or "").strip().lower()
    if env == "shibboleth":
        return "shibboleth"
    return "entra"


def _resolve_entra_mode(entra: EntraMode | None) -> EntraMode:
    if entra is not None:
        return entra
    env = (os.environ.get("LIST_ENTRA_MODE") or "").strip().lower()
    if env in ("device", "interactive", "auto"):
        return env  # type: ignore[return-value]
    # Browser first (user-friendly); device code only after timeout / failure.
    return "interactive"


def sign_in_api_key(base_url: str, api_key: str, *, api_version: int = 2) -> Client:
    """Sign in with a LiST API key, exchanging it for a JWT when possible."""
    base_url = base_url.rstrip("/")
    jwt, expiration = post_for_jwt(base_url, "auth/jwt/api", api_key=api_key)
    if jwt:
        return Client(
            base_url, api_key=api_key, jwt=jwt, api_version=api_version, jwt_expiration=expiration
        )
    logger.warning("POST /auth/jwt/api failed; continuing with X-API-Key only")
    return Client(base_url, api_key=api_key, jwt=None, api_version=api_version)


def sign_in_entra(
    base_url: str,
    *,
    api_version: int = 2,
    entra_mode: EntraMode = "interactive",
) -> Client:
    """
    Sign in via Microsoft Entra (MSAL) and exchange the Azure token for a LiST JWT.

    Needs Entra Mobile/desktop ``http://localhost`` + "Allow public client flows"
    for the interactive browser mode. Times out after 2 minutes if the window is
    closed, then falls back to device code. Pass ``entra_mode="device"`` to skip
    the browser outright.
    """
    base_url = base_url.rstrip("/")
    azure_token = _acquire_entra_token(base_url, entra_mode=entra_mode)
    print("Entra sign-in OK; exchanging Azure token for LiST JWT…", flush=True)
    jwt, expiration = post_for_jwt(
        base_url, "auth/jwt/api", bearer=azure_token, raise_on_error=True
    )
    if not jwt:
        raise RuntimeError(
            "Entra sign-in succeeded but POST /auth/jwt/api did not return a LiST JWT."
        )
    print("LiST JWT acquired.", flush=True)
    return Client(
        base_url, api_key=None, jwt=jwt, api_version=api_version, jwt_expiration=expiration
    )


def sign_in_shibboleth(
    base_url: str,
    *,
    api_version: int = 2,
    timeout_sec: float = _INTERACTIVE_TIMEOUT_SEC,
) -> Client:
    """
    Sign in via the campus Shibboleth SP (InCommon) and exchange the result for a LiST JWT.

    Opens a browser to ``{base_url}/auth/shibboleth-cli``, which is silent (no
    prompt) if you already have a campus SP session, and otherwise redirects you
    to your institution's login. The result comes back on a one-shot localhost
    listener as a one-time code, which is exchanged server-side for a JWT via
    ``POST /auth/jwt/shib`` — the code itself is never a usable credential.

    Requires the server to have the ``auth/shibboleth-cli`` / ``auth/jwt/shib``
    endpoints (not every LiST server does).
    """
    base_url = base_url.rstrip("/")
    state = secrets.token_urlsafe(24)
    code_box: dict[str, str] = {}
    done = threading.Event()

    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:  # silence default stderr logging
            pass

        def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            got_state = (params.get("state") or [""])[0]
            code = (params.get("code") or [""])[0]
            error = (params.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if error:
                self.wfile.write(
                    f"<html><body>Shibboleth sign-in failed: {error}. "
                    "You can close this tab.</body></html>".encode()
                )
            elif got_state != state or not code:
                self.wfile.write(
                    b"<html><body>Sign-in response did not match this request "
                    b"(possible tampering) - rejected. You can close this tab.</body></html>"
                )
            else:
                code_box["code"] = code
                self.wfile.write(
                    b"<html><body>Signed in. You can close this tab.</body></html>"
                )
            done.set()

    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    login_url = urljoin(base_url + "/", "auth/shibboleth-cli") + f"?port={port}&state={state}"
    print(
        "Opening a browser for Shibboleth (InCommon) sign-in.\n"
        "If you already have a campus session this should complete without a prompt.\n"
        f"Waiting up to {timeout_sec:.0f}s. Ctrl+C to cancel.",
        flush=True,
    )
    webbrowser.open(login_url)

    thread.join(timeout=timeout_sec)
    if not done.is_set():
        try:
            server.server_close()
        except OSError:
            pass
        raise RuntimeError(
            f"Shibboleth sign-in timed out after {timeout_sec:.0f}s "
            "(browser closed, or the server has no auth/shibboleth-cli endpoint)."
        )

    code = code_box.get("code")
    if not code:
        raise RuntimeError("Shibboleth sign-in was rejected or returned no code; see browser tab.")

    jwt, expiration = post_for_jwt(
        base_url, "auth/jwt/shib", json_body={"code": code}, raise_on_error=True
    )
    if not jwt:
        raise RuntimeError(
            "Shibboleth sign-in succeeded but POST /auth/jwt/shib did not return a LiST JWT."
        )
    print("LiST JWT acquired.", flush=True)
    return Client(
        base_url, api_key=None, jwt=jwt, api_version=api_version, jwt_expiration=expiration
    )


def _acquire_entra_token(base_url: str, *, entra_mode: EntraMode = "device") -> str:
    try:
        import msal
    except ImportError as exc:
        raise ImportError(
            "Entra sign-in requires msal. Install with: pip install 'listapi[entra]' "
            "or pip install msal"
        ) from exc

    msal_cfg = _fetch_msal_config(base_url)
    client_id = msal_cfg.get("clientId") or msal_cfg.get("ClientId")
    tenant_id = msal_cfg.get("tenantId") or msal_cfg.get("TenantId")
    instance = (msal_cfg.get("instance") or msal_cfg.get("Instance") or "").rstrip("/")
    scope = msal_cfg.get("scope") or msal_cfg.get("Scope")
    if not client_id or not tenant_id or not instance or not scope:
        raise RuntimeError(
            "system-config msalConfig is incomplete (need clientId, tenantId, instance, scope)"
        )

    authority = f"{instance}/{tenant_id}"
    scopes = [scope] if isinstance(scope, str) else list(scope)

    cache = msal.SerializableTokenCache()
    if MSAL_CACHE_PATH.is_file():
        cache.deserialize(MSAL_CACHE_PATH.read_text(encoding="utf-8"))

    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    result: dict[str, Any] | None = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result and "access_token" in result:
            _persist_msal_cache(cache)
            return str(result["access_token"])

    if entra_mode == "device":
        result = _acquire_token_device_code(app, scopes)
    else:
        # Browser first. Hard timeout: closing the window does not unblock MSAL's
        # localhost wait by itself.
        print(
            "Opening a browser for Microsoft sign-in.\n"
            "Complete sign-in and wait until the page says you can close it "
            f"(up to {_INTERACTIVE_TIMEOUT_SEC}s). Ctrl+C to cancel.",
            flush=True,
        )
        result = _acquire_token_interactive_with_timeout(
            app, scopes, timeout_sec=_INTERACTIVE_TIMEOUT_SEC
        )
        if result and "access_token" in result:
            _persist_msal_cache(cache)
            return str(result["access_token"])
        print(
            "Browser sign-in did not finish "
            "(closed early, or Entra missing Mobile/desktop http://localhost "
            "+ Allow public client flows).\n"
            "Falling back to device code…",
            flush=True,
        )
        result = _acquire_token_device_code(app, scopes)
    if not result or "access_token" not in result:
        err = (result or {}).get("error_description") or (result or {}).get("error") or result
        raise RuntimeError(
            f"Entra token acquisition failed: {err}\n"
            "Ops: enable 'Allow public client flows' on the Entra app. "
            "For browser login, also add a Mobile/desktop http://localhost redirect."
        )

    _persist_msal_cache(cache)
    return str(result["access_token"])


def _persist_msal_cache(cache: Any) -> None:
    if getattr(cache, "has_state_changed", False):
        MSAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MSAL_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _acquire_token_interactive_with_timeout(
    app: Any,
    scopes: list[str],
    *,
    timeout_sec: float,
) -> dict[str, Any] | None:
    """
    Run acquire_token_interactive in a daemon thread.

    Closing the browser does not unblock MSAL's localhost wait; we abandon after
    timeout_sec and leave the thread daemonized so the process can continue.
    """
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = app.acquire_token_interactive(scopes=scopes)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_run, name="listapi-msal-interactive", daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)
    if thread.is_alive():
        logger.warning(
            "Interactive Entra login still waiting after %ss (browser closed or "
            "localhost redirect not registered); abandoning",
            timeout_sec,
        )
        return None
    if "error" in box:
        logger.info("Interactive Entra login failed (%s)", box["error"])
        return None
    result = box.get("result")
    return result if isinstance(result, dict) else None


def _acquire_token_device_code(app: Any, scopes: list[str]) -> dict[str, Any] | None:
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise RuntimeError(
            f"Failed to create device flow: {flow}\n"
            "Enable 'Allow public client flows' on the Entra app registration."
        )
    print(flow["message"], flush=True)
    print("(Press Ctrl+C to cancel.)", flush=True)
    result = app.acquire_token_by_device_flow(flow)
    return result if isinstance(result, dict) else None


def _fetch_msal_config(base_url: str) -> dict[str, Any]:
    import requests

    url = urljoin(base_url + "/", "api/v1/system-config")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("system-config did not return an object")
    msal_cfg = data.get("msalConfig") or data.get("MsalConfig")
    if not isinstance(msal_cfg, dict):
        raise RuntimeError(
            "system-config has no msalConfig (Entra not configured on this server)"
        )
    return msal_cfg
