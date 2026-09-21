"""Create a sample, add a characterization activity, and upload a file.

Usage (dry illustration — fill real technique / instrument / researcherKey):

  python examples/pipeline_create.py --researcher-key USERKEY path/to/spectrum.csv

Requires write privileges and valid catalog ids on the target LiST server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import sign_in  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create sample + char activity + upload")
    parser.add_argument("file", type=Path, help="File to upload onto the new activity")
    parser.add_argument("--researcher-key", required=True, help="ResearcherKey for add-to-inventory")
    parser.add_argument("--technique", default=None, help="Char technique id")
    parser.add_argument("--instrument", default=None, help="Char instrument id")
    parser.add_argument(
        "--substrate-material-id",
        type=int,
        action="append",
        dest="substrate_material_ids",
        default=None,
        help="Substrate material id (repeatable)",
    )
    parser.add_argument("--description", default=None)
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    client = sign_in()
    create_kwargs: dict = {"researcher_key": args.researcher_key}
    if args.substrate_material_ids:
        create_kwargs["substrateMaterialIds"] = args.substrate_material_ids
    if args.description:
        create_kwargs["description"] = args.description

    sample = client.create_sample(**create_kwargs)
    label = sample.get("sampleLabel") or sample.get("SampleLabel")
    print(f"Created sample {label}")

    activity = client.add_activity(
        sample,
        kind="char",
        instrument=args.instrument,
        technique=args.technique,
        description=args.description,
    )
    aid = activity.get("id") or activity.get("ID")
    print(f"Created activity {aid}")

    uploaded = client.upload_file(activity, args.file)
    print("Uploaded:", uploaded.get("fileName") or uploaded.get("FileName") or uploaded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
