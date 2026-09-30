"""Shared helpers for exchanging credentials for a LiST JWT.

Used by both :mod:`listapi.auth` (initial sign-in) and :mod:`listapi.client`
(refresh of an already-issued JWT via ``POST auth/jwt/api``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests


def jwt_from_response(resp: requests.Response) -> str | None:
    """LiST JWT from a raw string body or a JSON ``token``/``access_token``/``jwt`` field."""
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
    return None


def parse_token_expiration(value: str | None) -> datetime | None:
    """Parse the server's ``X-Token-Expiration`` header (ISO 8601) to an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def post_for_jwt(
    base_url: str,
    path: str,
    *,
    api_key: str | None = None,
    bearer: str | None = None,
    json_body: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> tuple[str | None, datetime | None]:
    """POST ``path`` -> (LiST JWT, expiry from ``X-Token-Expiration``); (None, None) on failure.

    Never sends ambient cookies: a browser ``AuthToken`` cookie would make the
    server treat the request as cookie-authenticated, which blocks the
    anti-forgery bypass that ``auth/jwt/api`` (and ``auth/jwt/shib``) require.
    """
    url = urljoin(base_url + "/", path)
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        resp = requests.post(url, headers=headers, json=json_body, timeout=60, cookies={})
    except requests.RequestException as exc:
        msg = f"POST {url} request error: {exc}"
        if raise_on_error:
            raise RuntimeError(msg) from exc
        return None, None

    if not resp.ok:
        msg = (
            f"POST {url} failed with HTTP {resp.status_code}\n"
            f"  Reason: {resp.reason}\n"
            f"  Content-Type: {resp.headers.get('Content-Type')!r}\n"
            f"  Response body: {(resp.text or '').strip()[:1200] or '(empty)'}"
        )
        if raise_on_error:
            raise RuntimeError(msg)
        return None, None

    token = jwt_from_response(resp)
    if not token:
        msg = (
            f"POST {url} returned {resp.status_code} but body was not a JWT string.\n"
            f"  Content-Type: {resp.headers.get('Content-Type')!r}\n"
            f"  Body: {resp.text[:500]!r}"
        )
        if raise_on_error:
            raise RuntimeError(msg)
        return None, None

    return token, parse_token_expiration(resp.headers.get("X-Token-Expiration"))
