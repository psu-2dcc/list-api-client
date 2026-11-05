"""Push one or more files into the LiST input queue (Gatekeeper).

Usage:

  python examples/input_push.py scan.spm --instrument AFM1 --sample MBE2.123 --kind characterization
  python examples/input_push.py growth.log --instrument MCV2 --sample MCV2-261028A-CC --kind synthesis \\
      --external-key lab-mocvd/MCV2/2026-10-28/growth.log --source-path D:/Export/growth.log

Authentication: Gatekeeper API key (LIST_API_KEY / config). Default API version is 2 (required when the key
has no internal API). See docs/input-queue.md.
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
from listapi.input import (  # noqa: E402
    KINDS,
    InputFileEntry,
    InputMetadata,
    describe_input_status,
    file_sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="Files to push")
    parser.add_argument("--instrument", default=None, help="Synthesis or characterization instrument id")
    parser.add_argument("--sample", default=None, help="Sample label")
    parser.add_argument("--kind", choices=sorted(KINDS), default=None)
    parser.add_argument("--external-key", default=None, help="Idempotency key for the push / first file")
    parser.add_argument("--user", default=None, help="EPPN the data belongs to")
    parser.add_argument("--project", default=None, help="External project key (e.g. LEO)")
    parser.add_argument("--source-path", default=None, help="Original path on the instrument PC")
    parser.add_argument(
        "--with-sha256",
        action="store_true",
        help="Send files[].sha256 (server refuses on mismatch)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print metadata JSON, push nothing")
    add_auth_arguments(parser)
    args = parser.parse_args()

    for path in args.files:
        if not path.is_file():
            print(f"File not found: {path}", file=sys.stderr)
            return 1

    file_entries = [
        InputFileEntry(
            name=path.name,
            sha256=file_sha256(path) if args.with_sha256 else None,
        )
        for path in args.files
    ]
    meta = InputMetadata(
        external_key=args.external_key,
        kind=args.kind,
        instrument=args.instrument,
        sample=args.sample,
        user=args.user,
        project=args.project,
        source={"path": args.source_path} if args.source_path else None,
        files=file_entries,
    )
    if args.dry_run:
        print(meta.to_json_str())
        return 0

    client = sign_in_from_args(args)
    try:
        result = client.push_input(args.files, meta)
    except ListApiError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"submission {result.submission_id}  all_existing={result.all_existing}  HTTP {result.status_code}")
    for item in result.items:
        status = item.get("status") or item.get("Status")
        print(
            f"  #{item.get('id') or item.get('Id')}  {item.get('fileName') or item.get('FileName')}  "
            f"{status} ({describe_input_status(str(status or ''))})  "
            f"existing={item.get('existing') if item.get('existing') is not None else item.get('Existing')}"
        )
    status = client.input_ingest_status()
    print(f"ingest: count={status.get('count')} latest={status.get('latestReceived')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
