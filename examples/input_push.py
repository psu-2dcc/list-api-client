"""Push one or more files into the LiST input queue (Gatekeeper).

Usage (each file is ``path[:role]``; roles: sample-definition, recipe, log, data, characterization):

  python examples/input_push.py MBE2-run1.rcp:recipe --instrument MBE2 --user 0000-0002-1825-0097
  python examples/input_push.py run1.rcp:recipe run1.bin:log --instrument MBE2 --run-key 2026-10-28-1
  python examples/input_push.py scan.spm:characterization --instrument AFM1 --sample MCV2-261028A-CC

Authentication: Gatekeeper API key (LIST_API_KEY / config), sent on every call. See docs/input-queue.md.
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
from listapi.input import ROLES, InputMetadata, InputRun, describe_input_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="path[:role] (role: %s)" % ", ".join(sorted(ROLES)))
    parser.add_argument("--instrument", default=None, help="Synthesis or characterization instrument id")
    parser.add_argument("--sample", default=None, help="Sample label (optional for recipe/log/data)")
    parser.add_argument("--run-key", default=None, help="Stable key of the synthesis run")
    parser.add_argument("--external-key", default=None, help="Request-level idempotency key")
    parser.add_argument("--user", default=None, help="ORCID or EPPN the data belongs to")
    parser.add_argument("--project", default=None, help="External project key (e.g. LEO)")
    parser.add_argument("--source-path", default=None, help="Original path on the instrument PC")
    parser.add_argument("--dry-run", action="store_true", help="Print metadata JSON, push nothing")
    add_auth_arguments(parser)
    args = parser.parse_args()

    files = []
    for arg in args.files:
        path, _, role = arg.partition(":")
        if not Path(path).is_file():
            print(f"File not found: {path}", file=sys.stderr)
            return 1
        files.append((path, role) if role else Path(path))

    meta = InputMetadata(
        external_key=args.external_key,
        instrument=args.instrument,
        sample=args.sample,
        user=args.user,
        project=args.project,
        run=InputRun(key=args.run_key) if args.run_key else None,
        source={"path": args.source_path} if args.source_path else None,
    )
    if args.dry_run:
        print(meta.to_json_str())
        return 0

    client = sign_in_from_args(args)
    try:
        result = client.input.push(files, meta)
    except ListApiError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"submission {result.submission_id}  created={result.created}  HTTP {result.status_code}")
    for item in result.items:
        print(
            f"  #{item.id}  {item.file_name}  {item.status} "
            f"({describe_input_status(item.status or '')})  existing={item.existing}"
        )
    status = client.input.status()
    print(f"ingest: count={status.get('count')} latest={status.get('latestReceived')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
