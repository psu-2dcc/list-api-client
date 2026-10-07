"""Upload an HTML dashboard to one activity of a sample, checking the activity belongs to it.

Usage:

  python examples/upload_sample_dashboard.py MBE2.123 4711 dashboard.html
  python examples/upload_sample_dashboard.py MBE2.123 syn dashboard.html

SAMPLE is a sample label or numeric id. ACTIVITY is an activity id of that sample, or a
kind (`syn`, `char`, `split`) when the sample has exactly one activity of that kind.
If the activity is not found (or the kind is ambiguous) the sample's activities are listed.
Like upload_dashboard.py, the HTML must be self-contained (see README, "Dashboards").
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError, ids  # noqa: E402
from listapi.cli import add_auth_arguments, sign_in_from_args  # noqa: E402

_KINDS = ("syn", "char", "split")


def _describe(act: dict) -> str:
    parts = [
        str(act.get("activityType") or act.get("type") or ""),
        str(act.get("date") or act.get("activityDate") or "")[:10],
        str(act.get("description") or ""),
    ]
    return f"{ids.activity_id(act)}  " + "  ".join(p for p in parts if p)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload an HTML dashboard to a sample's activity")
    parser.add_argument("sample", help="Sample label or numeric id")
    parser.add_argument("activity", help="Activity id of that sample, or syn / char / split")
    parser.add_argument("file", type=Path, help="Self-contained .html / .htm file")
    parser.add_argument("--description", default=None)
    add_auth_arguments(parser)
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    try:
        client = sign_in_from_args(args)
        kind = args.activity.lower()
        if kind in _KINDS:
            matches = client.activities(args.sample, kind=kind)
        else:
            wanted = ids.activity_id(args.activity)
            matches = [a for a in client.activities(args.sample) if ids.activity_id(a) == wanted]
        if len(matches) != 1:
            what = "is ambiguous" if matches else "not found"
            print(f"Activity {args.activity!r} {what} on sample {args.sample}.", file=sys.stderr)
            for act in matches or client.activities(args.sample):
                print("  " + _describe(act), file=sys.stderr)
            return 1
        uploaded = client.upload_dashboard(matches[0], args.file, description=args.description)
    except (ListApiError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Uploaded to activity {ids.activity_id(matches[0])} of {args.sample}:")
    print("  file:", uploaded.get("fileName") or uploaded.get("FileName") or uploaded)
    print("  isDashboard:", uploaded.get("isDashboard"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
