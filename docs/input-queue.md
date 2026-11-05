# Pushing files into the LiST input queue (Gatekeeper)

A **Gatekeeper** is a lab machine whose API key may push data only for its instruments. The script on that
machine calls `POST api/v2/input` with file parts and optional `list-input/1` metadata. LiST stores each file
in `.input-queue`, then identifies and places it (characterization activity, attachment, …) in the background.

Instrument history events use a different route (`synthesis-instruments/{id}/events`); see
[instrument-history.md](instrument-history.md).

## Setup in LiST (admin)

1. **Customizing → Gatekeepers**: name, instruments (synthesis and/or characterization), optional default user.
2. A **role-based API key** belonging to that Gatekeeper, role with **InputQueue** Create (and
   **InstrumentHistory** Create/Update if the same key also pushes events). Gatekeeper keys normally have **no
   internal API** — they must use **api/v2**, which is this client's default.
3. Path rules / project mappings as needed so LiST can resolve instrument, sample and project from paths or
   metadata.

## Push

```python
from datetime import datetime, timezone
from listapi import sign_in_api_key
from listapi.input import KIND_CHARACTERIZATION, InputMetadata, file_sha256

client = sign_in_api_key("https://list.example.org", api_key)
path = "D:/AFM/2026/MCV2-261028A-CC/scan.spm"
meta = InputMetadata(
    external_key="lab-afm/2026-10-28/scan.spm",
    kind=KIND_CHARACTERIZATION,
    instrument="AFM1",
    sample="MCV2-261028A-CC",
    user="abc123@psu.edu",
    project="P-2026-014",
    acquired_at=datetime(2026, 10, 28, 9, 41, tzinfo=timezone.utc),
    source={"path": path},
    files=[{"name": "scan.spm", "sha256": file_sha256(path)}],
)
result = client.push_input([path], meta)
print(result.submission_id, result.all_existing, result.items)
print(client.input_ingest_status())
print(client.current_gatekeeper())  # instruments this key may push for
```

- **Idempotent**: same content + same external key → 200, `existing: true`, nothing stored again.
- **Kinds** (`listapi.input`): `sample-definition`, `synthesis`, `characterization`, `simulation`,
  `attachment`, or omit and let path rules decide.
- **Schema**: always `list-input/1` (constant `SCHEMA_V1`); full shape from `client.input_schema()`.
- **Status bookmark**: `client.input_ingest_status()` — counts per status (R/Q/W/F/D/…).
- **Lookup**: `client.find_input_items(submission_id=…)` or `external_key=…`; `client.get_input_item(id)`.

`examples/input_push.py` is a small CLI template.

Monitor endpoints (`POST input/search`, corrections, discard, retry) stay on **v1** for signed-in staff and are
not wrapped here; use `client.request(..., version=1)` if needed.
