"""Sample statistics (aggregated) for the same filters as find_samples.

Usage:
  python examples/sample_stats.py --syn-instrument MBE2 --grown-after 2026-01-01
  python examples/sample_stats.py --char-instrument XRD1 --char-technique XRD
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError, sign_in  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LiST sample statistics")
    parser.add_argument("--syn-instrument", default=None, help="Synthesis instrument id")
    parser.add_argument("--syn-technique", default=None, help="Synthesis technique id")
    parser.add_argument("--char-instrument", default=None, help="Characterization instrument id")
    parser.add_argument("--char-technique", default=None, help="Characterization technique id")
    parser.add_argument("--grown-after", default=None)
    parser.add_argument("--grown-before", default=None)
    parser.add_argument("--sample-id", default=None, help="Exact sample label")
    parser.add_argument("--limit", type=int, default=20, help="Max rows to print")
    args = parser.parse_args(argv)

    try:
        client = sign_in()
        rows = client.sample_stats(
            syn_instrument=args.syn_instrument,
            syn_technique=args.syn_technique,
            char_instrument=args.char_instrument,
            char_technique=args.char_technique,
            grown_after=args.grown_after,
            grown_before=args.grown_before,
            sample_id=args.sample_id,
        )
    except (ListApiError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"{len(rows)} stat row(s)")
    for row in rows[: args.limit]:
        print(json.dumps(row, default=str))
    if len(rows) > args.limit:
        print(f"... and {len(rows) - args.limit} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
