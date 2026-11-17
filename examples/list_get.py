"""GET a LiST API path and print the response (or save it with --out).

Usage:
  python examples/list_get.py users/current --api-version 1
  python examples/list_get.py samples/MBE2.123/notes --out notes.json
  python examples/list_get.py https://list.example.org/dotnet/api/v2/projects
  python examples/list_get.py samples/stats -p label=MBE2 -p page=2

The path is relative to /api/v{n}/ (default v2); absolute URLs also work.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError  # noqa: E402
from listapi.cli import add_auth_arguments, sign_in_from_args  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GET a LiST API path")
    parser.add_argument("path", help="path under /api/v{n}/, or a full http(s) URL")
    parser.add_argument("--api-version", type=int, default=None, help="API version (client default: 2)")
    parser.add_argument("-p", "--param", action="append", default=[], metavar="KEY=VALUE",
                        help="query parameter, repeatable")
    parser.add_argument("-o", "--out", default=None, help="write the response to this file instead of stdout")
    add_auth_arguments(parser)
    args = parser.parse_args(argv)

    try:
        params = dict(p.split("=", 1) for p in args.param)
    except ValueError:
        print("--param must look like KEY=VALUE", file=sys.stderr)
        return 2

    try:
        client = sign_in_from_args(args)
        data = client.get(args.path, version=args.api_version, params=params or None)
    except (ListApiError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    # client.get returns parsed JSON, None (empty body) or a raw Response (non-JSON).
    if data is None:
        body = b""
    elif hasattr(data, "content"):
        body = data.content
    else:
        body = json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if args.out:
        Path(args.out).write_bytes(body)
        print(f"Wrote {len(body)} bytes to {args.out}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(body + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
