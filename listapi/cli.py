"""Shared command-line options for scripts that sign in to LiST.

    parser = argparse.ArgumentParser()
    add_auth_arguments(parser)
    args = parser.parse_args()
    client = sign_in_from_args(args)   # prints "Sign-in cancelled." and exits on Ctrl+C

Without any option this behaves like :func:`listapi.sign_in` (API key from
env/config if present, else ``LIST_AUTH_METHOD``, default Entra).
"""

from __future__ import annotations

import argparse
import os
import sys

from listapi._jwt import post_for_jwt
from listapi.auth import sign_in
from listapi.client import Client
from listapi.config import load_list_config
from listapi.errors import SignInCancelled

_AUTH_CHOICES = ("api-key", "entra", "shibboleth", "none")


def add_auth_arguments(parser: argparse.ArgumentParser) -> None:
    """Add ``--url``, ``--auth`` and ``--entra-mode`` to ``parser``."""
    group = parser.add_argument_group("sign-in")
    group.add_argument(
        "--url",
        default=None,
        help="LiST base URL, including /dotnet (default: LIST_URL or config/list.py)",
    )
    group.add_argument(
        "--auth",
        choices=_AUTH_CHOICES,
        default=None,
        help=(
            "Sign-in method. Default: API key from LIST_API_KEY / config/list.py if set, "
            "otherwise LIST_AUTH_METHOD (entra unless set to shibboleth). "
            "An explicit choice overrides a configured API key. "
            "'none' sends no credentials (public data only; ignores any cached sign-in)."
        ),
    )
    group.add_argument(
        "--entra-mode",
        choices=("interactive", "device", "auto"),
        default=None,
        help="Entra only: browser (interactive, default) or device code (SSH / headless)",
    )


def sign_in_from_args(args: argparse.Namespace) -> Client:
    """Sign in using the options added by :func:`add_auth_arguments`.

    Ctrl+C or Cancel in the browser ends the program quietly with exit status 1
    (no traceback). Other sign-in failures propagate as exceptions.
    """
    if args.auth == "none":
        return _anonymous_client(_resolve_url(args.url))
    method = args.auth.replace("-", "_") if args.auth else None
    try:
        return sign_in(url=args.url, method=method, entra=args.entra_mode)
    except SignInCancelled as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None


def _resolve_url(url: str | None) -> str:
    """--url, else LIST_URL, else config/list.py (same order as :func:`listapi.sign_in`)."""
    if not url:
        url = os.environ.get("LIST_URL")
    if not url:
        try:
            url = load_list_config().get("url")
        except FileNotFoundError:
            pass
    if not url:
        raise SystemExit("LiST url is required (--url, LIST_URL, or config/list.py url=)")
    return str(url).rstrip("/")


def _anonymous_client(url: str) -> Client:
    """No credentials. Ask ``POST auth/jwt/api`` for an anonymous JWT; if the server
    refuses, continue with a bare client (works only where the server allows it)."""
    jwt, expiration = post_for_jwt(url, "auth/jwt/api")
    if not jwt:
        print(
            "No anonymous JWT from auth/jwt/api; continuing without a token.",
            file=sys.stderr,
        )
    return Client(url, jwt=jwt, jwt_expiration=expiration)
