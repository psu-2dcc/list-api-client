"""HTTP errors from the LiST API with a short, traceback-friendly message."""

from __future__ import annotations

from typing import Any

import requests


class ListApiError(Exception):
    """Raised for failed LiST API calls (especially 401 / 403 / 404)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: requests.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response

    @classmethod
    def from_response(cls, resp: requests.Response, what: str) -> ListApiError:
        status = resp.status_code
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
        return cls(msg, status_code=status, response=resp)


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
