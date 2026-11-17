"""HTTP errors from the LiST API with a short, traceback-friendly message."""

from __future__ import annotations

from typing import Any

import requests


class SignInCancelled(RuntimeError):
    """The user cancelled sign-in (Ctrl+C, or Cancel in the browser).

    A ``RuntimeError`` subclass, so existing ``except RuntimeError`` handlers
    keep working; catch this one first to treat cancelling as a non-error.
    """


class ListApiError(Exception):
    """Raised for failed LiST API calls (especially 401 / 403 / 404)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: requests.Response | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response
        #: The server's problem-details ``detail`` (or title / body text), without our prefix.
        self.detail = detail

    @classmethod
    def from_response(cls, resp: requests.Response, what: str) -> ListApiError:
        status = resp.status_code
        if 300 <= status < 400:
            return RedirectError.from_redirect(resp, what)
        detail = _problem_detail(resp) or (resp.reason or "")
        if status == 404:
            msg = f"{what}: not found (404)"
        elif status == 401:
            msg = f"{what}: unauthorized (401) — sign in again or check API key"
        elif status == 403:
            msg = f"{what}: forbidden (403) — no access"
        else:
            msg = f"{what} failed ({status})"
        if detail:
            msg = f"{msg}: {detail}"
        subclass = _BY_STATUS.get(status, cls) if cls is ListApiError else cls
        return subclass(msg, status_code=status, response=resp, detail=detail)


class RedirectError(ListApiError):
    """3xx: the server redirected the request instead of answering it.

    Redirects are not followed: a followed redirect turns a POST into a GET and
    drops the ``Authorization`` header when the host changes, which surfaces as a
    misleading 401. The usual fix is to use :attr:`location` (minus the API path)
    as the LiST base URL.
    """

    location: str = ""

    @classmethod
    def from_redirect(cls, resp: requests.Response, what: str) -> RedirectError:
        location = resp.headers.get("Location", "")
        msg = (
            f"{what}: redirected ({resp.status_code}) to {location or '(no Location header)'}"
            " — the LiST URL is probably not the canonical one; check the base URL"
            " (--url / LIST_URL / config)."
        )
        err = cls(msg, status_code=resp.status_code, response=resp, detail=location)
        err.location = location
        return err


class BadRequestError(ListApiError):
    """400: the server refused the request (no file, unusable metadata, sha256 mismatch, ...)."""


class ForbiddenError(ListApiError):
    """403: the key or user may not do this (e.g. an instrument that is not the Gatekeeper's)."""


class NotFoundError(ListApiError):
    """404: not found (for ``POST input``: the input queue is switched off)."""


class PayloadTooLargeError(ListApiError):
    """413: a file is larger than the server's limit (default 2048 MB)."""


class FeatureNotSupported(ListApiError):
    """The server build has no such feature (raised before the call; ``server`` holds its build info)."""

    def __init__(self, message: str, *, server: dict | None = None) -> None:
        super().__init__(message, status_code=404)
        self.server = server or {}


class RoleUnknown(ListApiError, ValueError):
    """A ``files[].role`` that is not one of :data:`listapi.input.ROLES` (raised before any request)."""


_BY_STATUS: dict[int, type[ListApiError]] = {
    400: BadRequestError,
    403: ForbiddenError,
    404: NotFoundError,
    413: PayloadTooLargeError,
}


def _problem_detail(resp: requests.Response) -> str:
    """Prefer ProblemDetails title/detail when the body is JSON."""
    text = (resp.text or "").strip()
    if not text:
        return ""
    try:
        data: Any = resp.json()
    except ValueError:
        return text[:500]
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("Detail")
        title = data.get("title") or data.get("Title")
        if detail and title and str(detail) != str(title):
            return f"{title}: {detail}"
        if detail:
            return str(detail)[:500]
        if title:
            return str(title)[:500]
    return text[:500]
