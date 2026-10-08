# listapi — Python client for the LiST REST API

Package name: **`listapi`**. Use it from scripts (or an MCP host) to sign in once, then search samples, pull activities/files, upload results, or call any Swagger route.

**For AI / coding agents:** install from GitHub, set `LIST_URL` + `LIST_API_KEY` (or Entra), then `from listapi import sign_in, ListApiError`. Prefer helpers below; fall back to `client.get` / `client.post` with paths from `{LIST_URL}/swagger`. Catch `ListApiError`. Do not use `""` for absent config — use `None` / omit.

---

## Install

**From GitHub (typical for agents and one-off scripts):**

```bash
pip install "git+https://github.com/psu-2dcc/list-api-client.git"
```

Extras:

```bash
# Microsoft browser / device-code sign-in (MSAL)
pip install "listapi[entra] @ git+https://github.com/psu-2dcc/list-api-client.git"

# MCP stdio server (Cursor / Claude Desktop)
pip install "listapi[mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
```

The GitHub repo is **public** — no token required for install.

**From a local clone:**

```bash
cd list-api-client   # or list-python
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
# optional: pip install -e ".[entra]" / pip install -e ".[mcp]"
```

Requires **Python ≥ 3.10**. Core dependencies: `requests`, `truststore` (verifies TLS against the OS certificate store so servers signed by an internal CA work; set `LISTAPI_NO_TRUSTSTORE=1` to opt out).

### Versioning

Bump **`version` in [`pyproject.toml`](pyproject.toml)** for every release (semver). After install, `listapi.__version__` matches that value.

| Change | Bump |
|--------|------|
| Bugfix / docs only | patch (`0.5.0` → `0.5.1`) |
| New helpers / MCP tools / compatible API | minor (`0.5.0` → `0.6.0`) |
| Breaking Client / `sign_in` behavior | major |

Pin a release from GitHub with a tag (preferred over floating `main`):

```bash
pip install "git+https://github.com/psu-2dcc/list-api-client.git@v0.7.0"
```

Create the matching git tag when you publish (`v0.7.0` for version `0.7.0`).

---

## Configure / sign in

Base URL is the same host as in the browser (include `/dotnet`). Default public instance:

`https://list.2dccmip.org/list/dotnet` — swap for staging or another instance when needed.

| Source | How |
|--------|-----|
| Env | `LIST_URL`, `LIST_API_KEY` (preferred for agents / CI) |
| Config file | `config/list.py` with `url` and `api_key` (see `config/list.py.example`); override dir with `LIST_CONFIG_DIR` |
| Args | `sign_in(url=..., api_key=...)` |

```python
from listapi import sign_in, ListApiError

client = sign_in()  # reads env / config
# or:
client = sign_in(url="https://list.2dccmip.org/list/dotnet", api_key="…")
```

| Mode | When |
|------|------|
| **API key** | Non-empty key from arg / `LIST_API_KEY` / config. Calls `POST /auth/jwt/api`, then sends `X-API-Key` (and Bearer JWT when obtained) on **every** request. |
| **Entra** | No API key, `method="entra"` (default) or `LIST_AUTH_METHOD=entra`. Needs `listapi[entra]`. Browser by default; `sign_in(entra="device")` or `LIST_ENTRA_MODE=device` for SSH. MSAL cache: `~/.list/msal_cache.bin`. |
| **Shibboleth** | No API key, `method="shibboleth"` or `LIST_AUTH_METHOD=shibboleth`. Opens a browser to your institution's login if needed, then asks you to confirm the sign-in for the shown account and local port (PKCE-protected, so it is never silent); needs a LiST server with the `auth/shibboleth-cli` / `auth/jwt/shib` endpoints. |

**How Shibboleth sign-in works.** `sign_in_shibboleth` opens `{url}/auth/shibboleth-cli` in the browser and listens once on `http://127.0.0.1:<port>/callback`. If you have no campus session you log in first; the server then shows "A program on this computer (local port N) wants to sign in to LiST as `<eppn>`" with **Continue** / **Cancel**. Only **Continue** sends a one-time code to the listener, so it is never silent, even with an existing session. The client exchanges the code at `POST auth/jwt/shib` together with a PKCE verifier (RFC 7636, S256, generated per sign-in and never sent through the browser), so a code intercepted on the loopback redirect is useless on its own. `state` is checked on every callback, including errors. Failures: **Cancel** (`access_denied`) and Ctrl+C raise `SignInCancelled`; `shibboleth_disabled`, `no_shibboleth_session` and `unknown_user` raise `RuntimeError`; no callback within 120 s (`timeout_sec=`) is a timeout error. A server without PKCE support ignores the extra parameters, so this client also works there; a PKCE-enforcing server rejects older clients (< 0.4.0) with HTTP 400 in the browser tab.

To force one method regardless of env/config, call `sign_in_api_key(url, api_key)`, `sign_in_entra(url, entra_mode=...)` or `sign_in_shibboleth(url)` directly instead of `sign_in()`.

However you signed in, the JWT is refreshed for you: `client.refresh()` exchanges a still-valid JWT for a new one via `POST auth/jwt/api`, and `Client.request` does this automatically (proactively near expiry, and once on a 401) — a long script generally never has to re-run sign-in.

After sign-in: `client.base_url`, `client.api_key`, `client.jwt` (may be `None`), `client.jwt_expiration` (server-set, may be `None`), default `client.api_version == 2`. Failures raise **`ListApiError`** (`status_code` 401 / 403 / 404 / …).

**API key source for humans:** LiST web → **About → FAQ** → ask that instance’s data manager.

---

## Minimal analysis script pattern

```python
from listapi import ListApiError, sign_in

def main() -> int:
    try:
        client = sign_in()  # LIST_URL + LIST_API_KEY in env
        sample = client.get_sample("MBE2.123")
        acts = client.activities(sample, kind="char", date="2026-09-21")
        for act in acts:
            for group in client.files(act):
                data = client.file_bytes(group)  # bytes — e.g. pandas.read_csv(io.BytesIO(data))
                print(act.get("id"), len(data))
    except ListApiError as exc:
        print(exc)
        return 1
    return 0
```

Search → stats → one sample (or `query_activities` for many) → activities → files is the usual read path. Repo examples: `examples/analyze_sample.py`, `examples/find_samples.py`, `examples/sample_stats.py`.

---

## What is available

Public imports: `from listapi import sign_in, Client, ListApiError` (plus import-status constants if needed).

### Auth

| Symbol | Role |
|--------|------|
| `sign_in(*, url=None, api_key=…, api_version=2, method=None, entra=None)` | Build authenticated `Client`; `method="api_key"\|"entra"\|"shibboleth"` is honoured even if a key is configured |
| `sign_in_api_key(url, api_key, *, api_version=2)` | Force API-key sign-in |
| `sign_in_entra(url, *, api_version=2, entra_mode="interactive")` | Force Entra sign-in |
| `sign_in_shibboleth(url, *, api_version=2, timeout_sec=120)` | Force Shibboleth sign-in |
| `Client(base_url, api_key=None, jwt=None, api_version=2, jwt_expiration=None)` | Direct construction if you already have credentials |
| `client.refresh()` | Exchange the current JWT for a new one (`POST auth/jwt/api`); returns `False` if there's nothing to refresh or it fails |
| `client.whoami()` | `GET api/v1/users/current` — `Id`, `Login`, `Eppn`, `AuthMethod` (`msal`/`shibboleth`/absent), roles, etc. for whoever is actually signed in |

### Generic HTTP (any Swagger route)

Paths are under `/api/v{api_version}/` unless you pass an absolute URL. Auth headers are already on the session.

| Method | Notes |
|--------|--------|
| `client.get(path, **kwargs)` | |
| `client.post(path, **kwargs)` | e.g. `json={...}` |
| `client.put` / `patch` / `delete` | |
| `client.request(method, path, *, version=None, **kwargs)` | Full control |

```python
projects = client.get("projects")
client.post("samples/add-to-inventory", json={...})
```

Discover routes: open `{url}/swagger` in a browser.

### Samples

| Method | Endpoint / behavior |
|--------|---------------------|
| `get_sample(sample)` | `GET samples/{idOrLabel}` — `sample` may be label, int id, or sample dict |
| `find_samples(...)` | `POST samples/search` — **auto-pages** all matches |
| `sample_stats(...)` | `POST sample-stat` — same filters, aggregated counts (needs SampleStatistics privilege) |
| `create_sample(**fields)` | `POST samples/add-to-inventory` — `researcher_key` alias for `researcherKey` |

**Shared search / stats filters** (`find_samples` and `sample_stats`):

| Argument | Maps to |
|----------|---------|
| `syn_instrument` / `syn_technique` | `instrumentId` / `techniqueId` |
| `char_instrument` / `char_technique` | `characterizationInstrumentId` / `characterizationTechniqueId` |
| `materials` | catalog material ids (`list[int]`) |
| `material_names` | names (server resolves) |
| `elements` | element symbols (server resolves when materials empty) |
| `grown_after` / `grown_before` | ISO dates |
| `sample_id` / `label` | exact `sampleLabel` |
| `page_size` | `find_samples` only (default 100) |
| `**criteria` | other camelCase `SampleSearchCriteria` fields (`projectId`, `addedAfter`, `search_kind` → `kind`, …) |

```python
rows = client.find_samples(syn_instrument="MBE2", grown_after="2026-01-01", char_technique="XRD")
stats = client.sample_stats(syn_instrument="MBE2", grown_after="2026-01-01")
```

### Notes (samples and activities)

Each method exists for samples (`*_sample_note*`, path `samples/{idOrLabel}/notes`) and for sample activities (`*_activity_note*`, path `sample-activities/{id}/notes`). The first argument is the sample (label, id or dict) or the activity (id or dict).

| Method | Endpoint / behavior |
|--------|---------------------|
| `get_sample_notes` / `get_activity_notes` | `GET …/notes` — only notes the caller may read |
| `save_sample_notes` / `save_activity_notes(owner, notes)` | `POST …/notes` — upsert per item (`id` null → insert); omitted notes are **not** deleted |
| `add_sample_note` / `add_activity_note(owner, title, text, *, visibility="U")` | Insert one note, return it as saved |
| `upsert_sample_note_by_title` / `upsert_activity_note_by_title(owner, title, text, *, visibility="U")` | Update the note with this exact title, else insert — idempotent for re-runs |
| `delete_sample_note` / `delete_activity_note(owner, note_id)` | `DELETE …/notes/{noteId}` |

`visibility`: `P` (on publication), `U` (user/PI, default), `I` (internal). `text` is HTML; the server sanitizes it on save (flattens `div` / `a`, keeps tables, images, inline styles), so compare against the stored note, not your local HTML, to detect changes.

```python
client.upsert_sample_note_by_title("MBE2.123", "Growth log", "<p>Substrate cleaned…</p>")
client.upsert_activity_note_by_title(4711, "XRD remarks", "<p>Peak shift at 2θ = 31°</p>")
```

### Activities

| Method | Notes |
|--------|--------|
| `query_activities(samples, *, processing_types=None, char_techniques=None, char_instruments=None)` | `POST samples/activities/query` — activities, recipes and file metadata for many samples in one call (see below) |
| `activities(sample, *, kind=None, instrument=None, technique=None, date=None, after=None, before=None)` | List + client-side filter. `kind`: `syn` \| `char` \| `split` |
| `get_sample_activities(sample)` | Raw list |
| `get_sample_activity(activity)` | One activity by id |
| `add_activity(sample, *, kind, instrument=None, technique=None, date=None, description=None, **fields)` | `kind`: `syn` or `char` |
| `update_sample_activity(activity, body, *, user_has_confirmed=False)` | PUT |

**Bulk query** — search, then fetch detailed activities for all hits at once instead of one `activities()` call per sample:

```python
samples = client.find_samples(syn_instrument="MBE2", grown_after="2026-01-01")
rows = client.query_activities(
    samples,                                  # sample dicts or numeric ids
    processing_types=["SYN"],                 # PREP | SYN | POST
    char_techniques=["XRD"],                  # optional
    char_instruments=["XRD1"],                # optional; must belong to char_techniques if both given
)
for row in rows:                              # {"sampleId", "sampleLabel", "activities": [...]}
    print(row["sampleLabel"], len(row["activities"]))
```

At least one of the three filters is required. Filters are independent (characterization technique + instrument use AND; contradictory combinations raise `ListApiError` 400). Samples that are unknown or unreadable are omitted; readable samples with no match get `activities == []`. Activities include recipes and file metadata (names, types, download URLs) but never file content — use `file_bytes` / `download`. Requests over 100 samples are split automatically.

### Files

| Method | Notes |
|--------|--------|
| `files(activity)` | File-group metadata |
| `file_bytes(file_or_url_or_activity)` | Download into memory (small CSV / spectra) |
| `file_stream(file_or_url)` | Streaming `Response` |
| `download(file_or_url, dest)` | Write to disk |
| `upload_file(activity, source, *, filename=None, description=None, metadata=None, visibility=None)` | Path, bytes, or file-like; `metadata` dict → custom file fields, `visibility` `P` / `U` / `I` |
| `update_file_metadata(activity, file, *, metadata=None, description=None, visibility=None, rename_to=None)` | Edit an uploaded file group (by id, basename or dict); `metadata` merges by label |
| `upload_activity_file` / `delete_activity_file` | Lower-level variants |

**File metadata.** Every uploaded file belongs to a *file group* (one basename, possibly several versions or formats), and the group carries a description, a visibility and a list of custom fields (label, value, optional type). `upload_file` sets them on upload, `update_file_metadata` changes them later:

```python
meta = client.upload_file(
    activity_id,
    "scan.csv",
    description="XRD scan, 2θ 10–80°",
    visibility="I",  # P = on publication, U = PI only, I = internal
    metadata={
        "Technique": "XRD",
        "Scan rate": {"value": 0.5, "type": "Number"},  # optional column type
        "Annealed": True,
    },
)
print(meta["id"], meta["basename"], meta["fields"])

client.update_file_metadata(activity_id, meta, metadata={"Technique": "XRD (grazing)"})
client.update_file_metadata(activity_id, "scan.csv", visibility="P")  # by basename
```

- `metadata` keys are the field labels (non-empty), in dict order. Values become strings: `None` → `""`, booleans → `"true"` / `"false"`, dates → ISO 8601, everything else `str()`. To set the column type as well, pass `{"value": ..., "type": "Number"}` (LiST column types such as `Text`, `Number`, `Time`).
- `visibility` takes `P` / `U` / `I` or the long names `OnPublication` / `UserPI` / `Internal`. Left out, the server default applies.
- `update_file_metadata` identifies the group by id, by basename, or by the dict `upload_file` / `files` returns. It merges fields by label: listed labels are set (value, type and order replaced), unlisted fields stay. Arguments left as `None` stay unchanged. `rename_to=` changes the basename and needs the id or dict, not the basename.
- **Re-uploading under an existing basename adds a version to that group, and the server ignores the `description`, `visibility` and `metadata` sent with it.** To change those, call `update_file_metadata` afterwards.
- Server routes: `POST …/sample-activities/{id}/files/upload` (multipart: `UploadFile`, `Description`, `Visibility`, `Fields[i].Label` / `.Value` / `.Type` / `.Order`) and `PUT …/sample-activities/{id}/file-groups` (JSON `FileMetaDataCreateOrUpdateRequest`). Both return a `FileMetaDataDto`.

Example: `examples/upload_with_metadata.py ACTIVITY_ID FILE --meta Technique=XRD --meta "Scan rate=0.5"` (or `--meta-json meta.json`; add `--update` to edit an existing file's metadata instead of uploading).

### Data packages

| Method | Notes |
|--------|--------|
| `get_data_package(id_or_doi)` | |
| `find_data_packages(**criteria)` | Auto-paged search; camelCase criteria from Swagger |

### Projects

| Method | Notes |
|--------|--------|
| `list_projects()` | Every project you can read (API v1); `category` is the PI institution class (`R1`, `NR1`, `G`, `Ind`, `Int`, `O`) |

### Publications

| Method | Notes |
|--------|--------|
| `list_publications()` | Every publication you can read |
| `get_publication(id_or_doi)` | Numeric id or DOI |
| `find_publications(*, search_text=None, elements=None, materials=None, publication_type=None, science_driver=None, date_from=None, date_to=None, work_type=None, drafts_only=False, instrument_doi=None)` | Auto-paged search; `publication_type` is `"I"` / `"E"` / `"L"`; dates as `yyyy[-MM[-dd]]` |
| `get_publication_data_packages(id_or_doi)` | Data packages attached to a publication |
| `lookup_doi(doi, *, include_raw=False)` | Crossref data as a draft (nothing saved); for existing publications `fieldDiffs` with Apply / Report / Error |
| `create_publication(request)` / `update_publication(request)` | Create (`submit: false` = draft) / full update (`id` in the request); `metadataFromCrossref: true` records a Crossref sync with the save |
| `render_publication(request)` | Server-rendered `authors` / `cite` preview |
| `suggest_authors(authors, *, publication_id=None)` | Match authors to LiST users, suggest highlights |

`lookup_doi`, `metadataFromCrossref`, `render_publication`, `suggest_authors` and the
date / author / funding fields need a LiST server with the extended publication API
(not on production yet).

### Sample import (automation)

| Method | Notes |
|--------|--------|
| `list_sample_imports(...)` | |
| `patch_import_outcome(...)` | |
| `submit_inline_definition(...)` | |

Import status helpers: `listapi.import_status` / re-exported constants (`STATUS_*`, `FILTER_*`, `describe_import_status`).

### Errors

```python
try:
    client.get_sample("nope")
except ListApiError as e:
    # e.status_code — 401 sign-in/key; 403 no access; 404 missing
    ...
```

---

## Local clone extras

If you cloned the repo (not only `pip install` from GitHub):

```bash
copy config\list.py.example config\list.py   # Windows
# cp config/list.py.example config/list.py
```

```bash
python examples/sample_metadata.py SAMPLE_ID
python examples/find_samples.py --syn-instrument MBE2 --grown-after 2026-01-01
python examples/sample_stats.py --syn-instrument MBE2 --grown-after 2026-01-01
python examples/analyze_sample.py SAMPLE_ID --date 2026-09-21
python examples/pipeline_create.py
python examples/upload_with_metadata.py ACTIVITY_ID scan.csv --meta Technique=XRD
```

Every example accepts the same sign-in options (from `listapi.cli`, reusable in your own scripts via `add_auth_arguments(parser)` / `sign_in_from_args(args)`):

| Option | Meaning |
|--------|---------|
| `--auth api-key\|entra\|shibboleth` | Force a method. Default: API key from `LIST_API_KEY` / `config/list.py` if set, else `LIST_AUTH_METHOD` (Entra unless `shibboleth`). An explicit choice overrides a configured key. |
| `--url URL` | LiST base URL (default `LIST_URL` / config) |
| `--entra-mode interactive\|device\|auto` | Entra only; `device` for SSH / headless |

```bash
python examples/sample_stats.py --auth shibboleth --url http://localhost:4000/dotnet
```

Ctrl+C (or **Cancel** in the browser) prints `Sign-in cancelled.` and exits with status 1. In your own code, catch `listapi.SignInCancelled` (a `RuntimeError`).

---

## MCP server (optional)

Expose LiST to **Cursor** or **Claude Desktop** via stdio MCP (sign in once, then read tools).

**Setup guide (install from GitHub, venv paths, both hosts):** [docs/MCP.md](docs/MCP.md)

```bash
pip install "listapi[mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
```
