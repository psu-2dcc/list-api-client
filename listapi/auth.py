"""Sign in to LiST: API key and/or Microsoft Entra (MSAL) → LiST JWT."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin

import requests

from listapi.client import Client
from listapi.config import load_list_config

logger = logging.getLogger(__name__)

MSAL_CACHE_PATH = Path.home() / ".list" / "msal_cache.bin"

# Interactive MSAL opens a browser and blocks on a localhost redirect. Closing the
# window does not cancel that wait — use a timeout, then fall back to device code.
_INTERACTIVE_TIMEOUT_SEC = 120

_UNSET = object()

EntraMode = Literal["device", "interactive", "auto"]


def sign_in(
    *,
    url: str | None = None,
    api_key: Any = _UNSET,
    api_version: int = 2,
    entra: EntraMode | None = None,
) -> Client:
    """
    Build an authenticated :class:`Client`.

    Config: ``config/list.py`` (override directory with ``LIST_CONFIG_DIR``).
    Env: ``LIST_URL``, ``LIST_API_KEY`` fill gaps when not passed explicitly.

    - If ``api_key`` is a non-empty string (arg, env, or config): ``X-API-Key``,
      then try ``POST /auth/jwt/api`` for a LiST JWT; on failure keep the key.
    - If ``api_key`` is ``None``: Entra **browser** login by default (needs Entra
      Mobile/desktop ``http://localhost`` + Allow public client flows). Times out
      after 2 minutes if the window is closed, then offers device code. Use
      ``entra="device"`` or ``LIST_ENTRA_MODE=device`` to skip the browser.
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
        return _sign_in_with_api_key(resolved_url, resolved_key, api_version=api_version)

    mode = _resolve_entra_mode(entra)
    return _sign_in_with_entra(resolved_url, api_version=api_version, entra_mode=mode)


def _resolve_entra_mode(entra: EntraMode | None) -> EntraMode:
    if entra is not None:
        return entra
    env = (os.environ.get("LIST_ENTRA_MODE") or "").strip().lower()
    if env in ("device", "interactive", "auto"):
        return env  # type: ignore[return-value]
    # Browser first (user-friendly); device code only after timeout / failure.
    return "interactive"


def _sign_in_with_api_key(base_url: str, api_key: str, *, api_version: int) -> Client:
    jwt = _exchange_list_jwt(base_url, api_key=api_key, azure_bearer=None)
    if jwt:
        return Client(base_url, api_key=api_key, jwt=jwt, api_version=api_version)
    logger.warning("POST /auth/jwt/api failed; continuing with X-API-Key only")
    return Client(base_url, api_key=api_key, jwt=None, api_version=api_version)


def _sign_in_with_entra(
    base_url: str,
    *,
    api_version: int,
    entra_mode: EntraMode = "device",
) -> Client:
    azure_token = _acquire_entra_token(base_url, entra_mode=entra_mode)
    print("Entra sign-in OK; exchanging Azure token for LiST JWT…", flush=True)
    jwt = _exchange_list_jwt(
        base_url, api_key=None, azure_bearer=azure_token, raise_on_error=True
    )
    if not jwt:
        raise RuntimeError(
            "Entra sign-in succeeded but POST /auth/jwt/api did not return a LiST JWT."
        )
    print("LiST JWT acquired.", flush=True)
    return Client(base_url, api_key=None, jwt=jwt, api_version=api_version)


def _exchange_list_jwt(
    base_url: str,
    *,
    api_key: str | None,
    azure_bearer: str | None,
    raise_on_error: bool = False,
) -> str | None:
    """POST /auth/jwt/api → LiST JWT string, or None on failure."""
    url = urljoin(base_url + "/", "auth/jwt/api")
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if azure_bearer:
        headers["Authorization"] = f"Bearer {azure_bearer}"
    try:
        # Do not send ambient cookies (browser AuthToken would block CanBypassAntiForgery).
        resp = requests.post(url, headers=headers, timeout=60, cookies={})
        if not resp.ok:
            msg = _format_jwt_exchange_failure(url, resp, azure_bearer)
            if raise_on_error:
                raise RuntimeError(msg)
            logger.debug("%s", msg)
            return None
        try:
            data = resp.json()
        except ValueError:
            data = resp.text.strip().strip('"')
        if isinstance(data, str) and data:
            return data
        if isinstance(data, dict):
            token = data.get("token") or data.get("access_token") or data.get("jwt")
            if isinstance(token, str) and token:
                return token
        msg = (
            f"POST {url} returned {resp.status_code} but body was not a JWT string.\n"
            f"  Content-Type: {resp.headers.get('Content-Type')!r}\n"
            f"  Body: {resp.text[:500]!r}"
        )
        if raise_on_error:
            raise RuntimeError(msg)
        logger.debug("%s", msg)
        return None
    except RuntimeError:
        raise
    except requests.RequestException as exc:
        msg = f"POST {url} request error: {exc}"
        if raise_on_error:
            raise RuntimeError(msg) from exc
        logger.debug("%s", msg)
        return None


def _format_jwt_exchange_failure(
    url: str,
    resp: requests.Response,
    azure_bearer: str | None,
) -> str:
    """Human-readable failure for POST /auth/jwt/api (status, body, Azure token claims)."""
    lines = [
        f"POST {url} failed with HTTP {resp.status_code}",
        f"  Reason: {resp.reason}",
        f"  Content-Type: {resp.headers.get('Content-Type')!r}",
    ]
    body = (resp.text or "").strip()
    if body:
        lines.append(f"  Response body:\n{body[:1200]}")
    else:
        lines.append("  Response body: (empty)")
    if azure_bearer:
        lines.append(_azure_token_hint(azure_bearer).lstrip("\n") or "  Azure token: (could not decode)")
        lines.append(
            "  Note: React uses GET /auth/jwt/app with the same Azure bearer; "
            "compare aud/iss/scp above to a working browser token if this keeps failing."
        )
    return "\n".join(lines)


def _azure_token_hint(azure_bearer: str) -> str:
    """Decode JWT payload claims for debugging (no signature check)."""
    try:
        import base64
        import json

        parts = azure_bearer.split(".")
        if len(parts) < 2:
            return "  Azure token: not a JWT"
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return (
            "  Azure access token claims:\n"
            f"    aud = {payload.get('aud')!r}\n"
            f"    iss = {payload.get('iss')!r}\n"
            f"    scp = {payload.get('scp')!r}\n"
            f"    appid / azp = {payload.get('appid') or payload.get('azp')!r}\n"
            f"    upn / preferred_username = "
            f"{payload.get('upn') or payload.get('preferred_username')!r}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"  Azure token: decode failed ({exc})"


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
