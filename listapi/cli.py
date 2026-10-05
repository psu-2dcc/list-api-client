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
import sys

from listapi.auth import sign_in
from listapi.client import Client
from listapi.errors import SignInCancelled

_AUTH_CHOICES = ("api-key", "entra", "shibboleth")


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
            "An explicit choice overrides a configured API key."
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
    method = args.auth.replace("-", "_") if args.auth else None
    try:
        return sign_in(url=args.url, method=method, entra=args.entra_mode)
    except SignInCancelled as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
