# Pushing files into the LiST input queue (Gatekeeper)

A **Gatekeeper** is a lab machine whose API key may push data only for its instruments. The script on that
machine calls `client.input.push(...)` (`POST api/v2/input`, multipart). LiST stores each file in
`.input-queue`, then identifies and places it (synthesis, characterization, attachment, ...) in the background.

The client **never says synthesis or characterization and never reads a recipe or data file**: it tells LiST each
file's **role**; LiST decides the rest.

Instrument history events use a different route (`synthesis-instruments/{id}/events`); see
[instrument-history.md](instrument-history.md).

## Setup in LiST (admin)

1. **Customizing → Gatekeepers**: name, instruments, optional default user.
2. A **role-based API key** belonging to that Gatekeeper, role with **InputQueue** Create (and
   **InstrumentHistory** Create/Update if the same key also pushes events).

## Authentication

```python
from listapi import sign_in
client = sign_in("https://list.example.org", api_key=gatekeeper_key)   # or Client(url, api_key=...)
```

The key is sent as `X-API-Key` **on every call**. It is never exchanged for a JWT (`auth/jwt/api` refuses
API keys) and Entra is not tried. Gatekeeper keys work on **api/v2** only (v1 answers 403) and only for their
Gatekeeper's instruments (403 otherwise). `client.get/post/...` use the client's `api_version` (default 2);
v1-only helpers such as `whoami()` or `list_projects()` will be refused for such a key.

## Which server?

The input queue only exists on builds that have it (and it is off by default in the server config).
`client.server_info()` reports the build (`branch`, `commitHash`, `buildDate`, `version`, `environment`) from the
anonymous `system-config`; the build `version` is not a feature level, so the client asks the feature itself:

- `client.input.supported()` probes `GET input/schema` once: `True` (build has it), `False` (404: no input API),
  `None` (could not tell).
- On `False`, every `client.input` call raises `FeatureNotSupported` **before** anything is read or uploaded, with the
  server's branch and commit in the message. On `None` the call is attempted anyway.
- A build that has the queue but has it switched off answers the push with `NotFoundError` ("The input queue is off").
- `client.input.check_server = False` skips the probe.

## `client.input`

| Method | HTTP |
| --- | --- |
| `push(files, metadata=None)` | `POST input` → `PushResult(submission_id, items, created)`; 202 → `created=True`, 200 → `False` |
| `push_folder(path, instrument, role_by_glob=...)` | one request for a run folder; skips what `exists` says is known |
| `exists(items)` | `POST input/exists`, ≤ 500 per call (larger lists are split) |
| `status()` | `GET input/ingest-status`: count, latest received, count per status |
| `get(item_id)` | `GET input/{id}`, own items only |
| `find(submission_id=… \| external_key=…)` | `GET input`, newest first, ≤ 500 |
| `schema()` | `GET input/schema`: JSON Schema of `list-input/1` |
| `wait(submission_id, timeout)` | polls `find` until no item is received/queued/moving |

Not wrapped (staff, v1): search, retry, corrections, discard.

### `push` does the boring parts

- **sha256** of every file is computed (in chunks) and sent in `files[].sha256`; the server refuses the request
  on a mismatch, so a broken upload is detected, not stored.
- **One request per logical push**: files of one request share a `submissionId` and keep the order you give.
  Put the files that belong together in one call, definition or recipe first.
- **`externalKey`** makes a push idempotent: same key + same content is a no-op (200), same key + new content
  replaces. Default per file: `{instrument}/{role}/{fileName}`, or `{instrument}/{run.key}/{role}/{fileName}` when the
  metadata has a `run.key` (unique per instrument; a name repeating per run must not replace the earlier run's
  file). Without a run key, give your own when a name repeats, e.g. `MBE2/2026-10-28/run1/growth.log` (`PushFile(..., external_key=...)`), or set a
  request-level `external_key` (LiST appends `/{fileName}`; no default is added then).
- **Streaming**: the body is streamed from disk; nothing is read into memory. Timeouts are (30 s connect, 30 min
  read), adjustable with `client.input.timeout`.
- **Retries**: network errors and 5xx/503, with backoff (`client.input.retries`, `.backoff`). A retry of a push
  that had succeeded answers 200.
- **Errors** (all `ListApiError`, with `status_code` and the server's `detail`): 400 `BadRequestError`,
  403 `ForbiddenError`, 404 `NotFoundError` (queue off), 413 `PayloadTooLargeError` (default limit 2048 MB).
  Nothing is stored on an error. An unknown role raises `RoleUnknown` before any request.

### Files

`files` accepts a path, `(path, role)`, `(name, bytes_or_stream, role)` or `PushFile(source, role=…, name=…,
external_key=…, sha256=…, fields=…)`.

**Roles** (`listapi.ROLES`): `sample-definition`, `recipe`, `log`, `data`, `characterization`.
`data` is a companion of a log (same base name, e.g. the recorder `.csv`); it lands on the log's activity and
does not wait for it. Without any role LiST falls back to the instrument (only a characterization instrument:
characterization; only a synthesis instrument: log); an id that is both is `InstrumentAmbiguous`. A definition,
recipe or `data` file always needs a role. An unknown role fails only that file on the server (`RoleUnknown`).

### Metadata (`list-input/1`)

`InputMetadata` (or a plain dict) - all fields optional, absent values are **omitted** (never `""`):
`external_key`, `instrument`, `sample`, `user`, `project`, `acquired_at`, `run`, `source`, `description`,
`fields`, `files`.

- `sample` is optional for `recipe`, `log` and `data` (taken from a definition in the same request, derived by a
  script, or the item waits: `SampleUnresolved`); still needed for `characterization` and attachments.
- `user`: an **ORCID** (bare or `https://orcid.org/...`) or an **EPPN** - what the operator's sign-in gives. An
  unknown user is a warning, never a failure.
- `run` (`InputRun(key=…, index=…, start=…)`): names the synthesis run among a sample's runs. **Not implemented on
  the server yet** (phase 11d); do not rely on it before that ships. Per-file `run`, `acquiredAt`, `sample`,
  `characterizationId` overrides are planned with it.
- Times carry an offset; a naive time is read as the server's local time. There is no `provenance` block and no
  request-level `kind` (ignored by the server).

## Examples

```python
# 1. Recipe only, sample unknown (a derive rule makes the sample)
client.input.push([("MBE2-run1.rcp", "recipe")], metadata={"instrument": "MBE2", "user": orcid})

# 2. Raw log and recipe of one growth (the log may be binary; the server converts it with a rule)
client.input.push(
    [("run1.rcp", "recipe"), ("run1.bin", "log")],
    metadata={"instrument": "MBE2", "run": {"key": "2026-10-28-1"}},
)

# 3. Two raw files, one optional (csv always, log sometimes): push whatever exists now; the other may
#    come in a later request. LiST runs the dashboard script when the required file is there and does
#    not rerun it when the optional one arrives later.
client.input.push([("run1.csv", "data")], {"instrument": "MBE2"})
client.input.push([("run1.log", "log")], {"instrument": "MBE2"})

# 4. Definition + recipes + log in one request (instruments that write a definition XML)
client.input.push(
    [("S1.xml", "sample-definition"), ("a.rcp", "recipe"), ("b.rcp", "recipe"), ("growth.log", "log")],
    metadata={"instrument": "MBE2", "user": orcid},
)

# A run folder appeared
client.input.push_folder("D:/Export/MBE2/2026/run1", "MBE2")

# Lost the local record? Ask before re-sending gigabytes
known = {r.external_key for r in client.input.exists([(key, sha) for key, sha in pending]) if r.known}

# In tests: follow the items to the end
for item in client.input.wait(result.submission_id, timeout=120):
    print(item.id, item.status, item.error_code)
```

## Item statuses and error codes

| Status | Meaning |
| --- | --- |
| `R` received, `Q` queued, `M` moving | in progress |
| `W` waiting | may fix itself; LiST retries |
| `F` failed | needs a correction by a person |
| `D` done | placed |
| `X` discarded, `U` duplicate | closed |

Error codes on an item: **waiting, retried by LiST** - `SampleNotFound`, `SampleUnresolved`, `RunNotFound`,
`InstrumentUnknown`; **need a person** - `KindUnknown`, `RoleUnknown`, `InstrumentAmbiguous`, `InvalidFormat`,
`NotAllowed` (`listapi.input.WAITING_ERROR_CODES` / `NEEDS_PERSON_ERROR_CODES`).

`examples/input_push.py` is a small CLI template. Tests: `python -m unittest discover -s tests`.
