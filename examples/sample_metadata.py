"""Fetch and print sample metadata.

Usage:
  python examples/sample_metadata.py SAMPLE_ID

Requires config/list.py (copy from config/list.py.example).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running without pip install -e .
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError, sign_in  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print LiST sample metadata as JSON")
    parser.add_argument("sample_id", help="Sample label or numeric id")
    args = parser.parse_args(argv)

    try:
        client = sign_in()
        sample = client.get_sample(args.sample_id)
    except (ListApiError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(json.dumps(sample, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
