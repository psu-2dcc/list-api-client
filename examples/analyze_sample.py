"""Fetch characterization files for a sample on a given date (analysis starter).

Usage:
  python examples/analyze_sample.py SAMPLE_ID --date YYYY-MM-DD

Loads file bytes into memory so you can hand them to pandas / local logic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError, sign_in  # noqa: E402
from listapi.ids import file_download_url  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load char activity files for analysis")
    parser.add_argument("sample_id", help="Sample label or numeric id")
    parser.add_argument("--date", required=True, help="Activity date (YYYY-MM-DD)")
    parser.add_argument("--instrument", default=None, help="Optional char instrument id")
    parser.add_argument("--technique", default=None, help="Optional char technique id")
    args = parser.parse_args(argv)

    try:
        client = sign_in()
        acts = client.activities(
            args.sample_id,
            kind="char",
            date=args.date,
            instrument=args.instrument,
            technique=args.technique,
        )
    except (ListApiError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if not acts:
        print(f"No characterization activities on {args.date} for {args.sample_id}")
        return 1

    for act in acts:
        aid = act.get("id") or act.get("ID")
        print(f"Activity {aid}")
        for group in client.files(act):
            try:
                url = file_download_url(group)
            except ValueError:
                nested = group.get("files") or group.get("Files") or []
                for row in nested:
                    if not isinstance(row, dict):
                        continue
                    name = row.get("fileName") or row.get("FileName") or "file"
                    data = client.file_bytes(row)
                    print(f"  {name}: {len(data)} bytes")
                    # --- put analysis here (e.g. pandas.read_csv(io.BytesIO(data))) ---
                continue
            name = group.get("fileName") or group.get("FileName") or Path(url).name
            data = client.file_bytes(url)
            print(f"  {name}: {len(data)} bytes")
            # --- put analysis here ---

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
