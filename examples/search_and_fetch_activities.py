"""Search samples, then fetch activities (with recipes) for all matches.

Step 1: client.find_samples(...)      -> discovery by instrument/technique/date/material
Step 2: client.query_activities(...)  -> activities + recipes for every hit
        (batched automatically at 100 samples per request)

query_activities needs at least one filter: --processing-types and/or
--char-techniques / --char-instruments.

Usage:
  python examples/search_and_fetch_activities.py --syn-instrument MBE2 --grown-after 2026-07-01
  python examples/search_and_fetch_activities.py --syn-instrument MBE2 --processing-types SYN POST
  python examples/search_and_fetch_activities.py --char-technique XRD --char-techniques XRD --out xrd.json
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


BATCH = 100  # server maximum per activities/query call


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search samples, then fetch their activities")
    # Search criteria (step 1)
    parser.add_argument("--syn-instrument", default=None, help="Synthesis instrument id")
    parser.add_argument("--syn-technique", default=None, help="Synthesis technique id")
    parser.add_argument("--char-instrument", default=None, help="Characterization instrument id")
    parser.add_argument("--char-technique", default=None, help="Characterization technique id")
    parser.add_argument("--elements", nargs="+", default=None, help="Element symbols, e.g. Mo S")
    parser.add_argument("--grown-after", default=None)
    parser.add_argument("--grown-before", default=None)
    # Activity filters (step 2)
    parser.add_argument(
        "--processing-types", nargs="+", default=None, choices=["PREP", "SYN", "POST"],
        help="Activity types to fetch (default: SYN if no char filter is given)",
    )
    parser.add_argument("--char-techniques", nargs="+", default=None)
    parser.add_argument("--char-instruments", nargs="+", default=None)
    parser.add_argument("--max-samples", type=int, default=None, help="Cap samples fetched")
    parser.add_argument("--out", default=None, help="Write full results to this JSON file")
    add_auth_arguments(parser)
    args = parser.parse_args(argv)

    processing_types = args.processing_types
    if not (processing_types or args.char_techniques or args.char_instruments):
        processing_types = ["SYN"]  # server requires at least one filter

    try:
        print("Signing in (a browser window may open)...", file=sys.stderr, flush=True)
        client = sign_in_from_args(args)
        print(client.whoami_str(), flush=True)

        print("Searching samples (paging 100 at a time)...", file=sys.stderr, flush=True)
        samples = client.find_samples(
            syn_instrument=args.syn_instrument,
            syn_technique=args.syn_technique,
            char_instrument=args.char_instrument,
            char_technique=args.char_technique,
            elements=args.elements,
            grown_after=args.grown_after,
            grown_before=args.grown_before,
            limit=args.max_samples,  # stop paging once we have enough
        )
        capped = args.max_samples is not None and len(samples) >= args.max_samples
        print(f"{len(samples)} sample(s) {'(capped by --max-samples) ' if capped else ''}matched")
        if not samples:
            return 0

        rows = []
        for i in range(0, len(samples), BATCH):
            rows += client.query_activities(
                samples[i : i + BATCH],
                processing_types=processing_types,
                char_techniques=args.char_techniques,
                char_instruments=args.char_instruments,
            )
            print(f"  fetched activities for {min(i + BATCH, len(samples))}/{len(samples)} samples", flush=True)
    except (ListApiError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    total = 0
    for row in rows:
        acts = row.get("activities") or []
        total += len(acts)
        print(f"{row.get('sampleLabel')}: {len(acts)} activit{'y' if len(acts) == 1 else 'ies'}")
    print(f"{len(rows)} sample(s) returned, {total} activities total")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
