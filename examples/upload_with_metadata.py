"""Upload a data file onto a sample activity with custom file metadata.

Usage:

  python examples/upload_with_metadata.py ACTIVITY_ID scan.csv --meta Technique=XRD --meta "Scan rate=0.5"
  python examples/upload_with_metadata.py ACTIVITY_ID scan.csv --meta-json meta.json --visibility I
  python examples/upload_with_metadata.py ACTIVITY_ID scan.csv --meta Technique=Raman --update

Each --meta LABEL=VALUE becomes one metadata field on the file (in the order given).
--meta-json reads a JSON object instead; a value may be {"value": 0.5, "type": "Number"}.
--update edits the metadata of the file already uploaded under that name instead of
uploading (re-uploading under an existing name adds a version and keeps the old metadata).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from listapi import ListApiError  # noqa: E402
from listapi.cli import add_auth_arguments, sign_in_from_args  # noqa: E402


def _parse_meta(pairs: list[str], json_path: Path | None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if json_path is not None:
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{json_path} must contain a JSON object")
        meta.update(loaded)
    for pair in pairs:
        label, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f"--meta expects LABEL=VALUE, got {pair!r}")
        meta[label.strip()] = value
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload a file with metadata to a sample activity")
    parser.add_argument("activity_id", help="Sample activity id")
    parser.add_argument("file", type=Path, help="File to upload")
    parser.add_argument("--meta", action="append", default=[], metavar="LABEL=VALUE")
    parser.add_argument("--meta-json", type=Path, default=None, help="JSON object of metadata")
    parser.add_argument("--description", default=None)
    parser.add_argument("--visibility", default=None, help="P (on publication), U (PI only), I (internal)")
    parser.add_argument(
        "--update", action="store_true", help="Edit the existing file's metadata instead of uploading"
    )
    add_auth_arguments(parser)
    args = parser.parse_args(argv)

    if not args.update and not args.file.is_file():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    try:
        metadata = _parse_meta(args.meta, args.meta_json)
        client = sign_in_from_args(args)
        if args.update:
            result = client.update_file_metadata(
                args.activity_id,
                args.file.name,
                metadata=metadata,
                description=args.description,
                visibility=args.visibility,
            )
        else:
            result = client.upload_file(
                args.activity_id,
                args.file,
                description=args.description,
                metadata=metadata,
                visibility=args.visibility,
            )
    except (ListApiError, ValueError, RuntimeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print("File group:", result.get("id"), result.get("basename"))
    for field in result.get("fields") or []:
        print(f"  {field.get('label')}: {field.get('value')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
