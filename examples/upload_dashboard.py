"""Upload a self-contained HTML dashboard onto a sample activity.

Usage:

  python examples/upload_dashboard.py ACTIVITY_ID path/to/dashboard.html
  python examples/upload_dashboard.py ACTIVITY_ID dashboard.html --description "XRD overview"

LiST shows the file in the activity view (a plain `upload_file` would only attach it).
The HTML must be self-contained: inline script/style, images and fonts as data: URIs,
no external resources. Requires write privileges on a non-submitted sample activity.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError  # noqa: E402
from listapi.cli import add_auth_arguments, sign_in_from_args  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload an HTML dashboard to a sample activity")
    parser.add_argument("activity_id", help="Sample activity id")
    parser.add_argument("file", type=Path, help="Self-contained .html / .htm file")
    parser.add_argument("--description", default=None)
    add_auth_arguments(parser)
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    try:
        client = sign_in_from_args(args)
        uploaded = client.upload_dashboard(
            args.activity_id, args.file, description=args.description
        )
    except (ListApiError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print("Uploaded:", uploaded.get("fileName") or uploaded.get("FileName") or uploaded)
    print("isDashboard:", uploaded.get("isDashboard"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
