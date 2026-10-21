"""Template for a script at an instrument: push the instrument's event log to its LiST history.

Copy this file to the instrument PC and adapt ``read_events`` to the instrument's log. Run it on a schedule
(Task Scheduler, cron); every run reads the whole log (or the recent part) and pushes it again. That is safe:
LiST finds each event by its external key and only changes what changed, so the script keeps no state.

Usage:

  python examples/instrument_log_push.py MBE2 events.csv              # API key from LIST_API_KEY / config/list.py
  python examples/instrument_log_push.py MBE2 events.csv --dry-run

The example log is a CSV with columns ``id,type,start,end,title,description`` (start/end ISO 8601, end empty for
a point in time). ``TYPE_MAP`` maps the instrument's own type names to LiST event types (Customizing →
Instrument event types). Without an ``id`` column, ``stable_key`` builds a key from type and start.

Authentication: a role-based API key that lists the instrument (an admin creates it in LiST: API keys →
"Instrument history") with a role that has the privilege InstrumentHistory. See docs/instrument-history.md.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError  # noqa: E402
from listapi.cli import add_auth_arguments, sign_in_from_args  # noqa: E402
from listapi.instruments import InstrumentEvent, InstrumentPushError, stable_key  # noqa: E402

# The instrument's event names → LiST event type IDs. Unknown names become OTHER.
TYPE_MAP = {
    "maintenance": "MAINT",
    "cleaning": "CLEAN",
    "bakeout": "BAKE",
    "calibration": "CALIB",
}


def read_events(log: Path) -> list[InstrumentEvent]:
    """Adapt this to the instrument's log format."""
    events = []
    with log.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind = (row.get("type") or "").strip().lower()
            start = datetime.fromisoformat(row["start"])
            end = datetime.fromisoformat(row["end"]) if row.get("end") else None
            key = row.get("id") or stable_key(kind, start.isoformat(), prefix=log.stem)
            events.append(
                InstrumentEvent(
                    external_key=key,
                    event_type=TYPE_MAP.get(kind, "OTHER"),
                    start=start,
                    end=end,
                    title=row.get("title") or kind.capitalize() or "Event",
                    description=row.get("description") or None,
                )
            )
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instrument", help="Synthesis instrument ID in LiST, e.g. MBE2")
    parser.add_argument("log", type=Path, help="The instrument's event log")
    parser.add_argument("--dry-run", action="store_true", help="Read and print the events, push nothing")
    add_auth_arguments(parser)
    args = parser.parse_args()

    events = read_events(args.log)
    print(f"{len(events)} event(s) in {args.log}")
    if args.dry_run:
        for e in events:
            print(f"  {e.external_key}  {e.event_type:6}  {e.start.isoformat()}  {e.title}")
        return 0

    client = sign_in_from_args(args)
    try:
        result = client.push_instrument_events(args.instrument, events)
    except InstrumentPushError as e:
        print(e, file=sys.stderr)
        return 2
    except ListApiError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"created {result.created}, updated {result.updated}, unchanged {result.unchanged}")
    status = client.instrument_ingest_status(args.instrument)
    print(f"{status['eventCount']} pushed event(s) on {args.instrument}, latest start {status['latestEventStart']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
