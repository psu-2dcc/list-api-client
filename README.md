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

Requires **Python ≥ 3.10**. Core dependency: `requests`.

### Versioning

Bump **`version` in [`pyproject.toml`](pyproject.toml)** for every release (semver). After install, `listapi.__version__` matches that value.

| Change | Bump |
|--------|------|
| Bugfix / docs only | patch (`0.2.0` → `0.2.1`) |
| New helpers / MCP tools / compatible API | minor (`0.2.0` → `0.3.0`) |
| Breaking Client / `sign_in` behavior | major |

Pin a release from GitHub with a tag (preferred over floating `main`):

```bash
pip install "git+https://github.com/psu-2dcc/list-api-client.git@v0.2.0"
```

Create the matching git tag when you publish (`v0.2.0` for version `0.2.0`).

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
| **Entra** | No API key. Needs `listapi[entra]`. Browser by default; `sign_in(entra="device")` or `LIST_ENTRA_MODE=device` for SSH. MSAL cache: `~/.list/msal_cache.bin`. |

After sign-in: `client.base_url`, `client.api_key`, `client.jwt` (may be `None`), default `client.api_version == 2`. Failures raise **`ListApiError`** (`status_code` 401 / 403 / 404 / …).

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

Search → stats → one sample → activities → files is the usual read path. Repo examples: `examples/analyze_sample.py`, `examples/find_samples.py`, `examples/sample_stats.py`.

---

## What is available

Public imports: `from listapi import sign_in, Client, ListApiError` (plus import-status constants if needed).

### Auth

| Symbol | Role |
|--------|------|
| `sign_in(*, url=None, api_key=…, api_version=2, entra=None)` | Build authenticated `Client` |
| `Client(base_url, api_key=None, jwt=None, api_version=2)` | Direct construction if you already have credentials |

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

### Activities

| Method | Notes |
|--------|--------|
| `activities(sample, *, kind=None, instrument=None, technique=None, date=None, after=None, before=None)` | List + client-side filter. `kind`: `syn` \| `char` \| `split` |
| `get_sample_activities(sample)` | Raw list |
| `get_sample_activity(activity)` | One activity by id |
| `add_activity(sample, *, kind, instrument=None, technique=None, date=None, description=None, **fields)` | `kind`: `syn` or `char` |
| `update_sample_activity(activity, body, *, user_has_confirmed=False)` | PUT |

### Files

| Method | Notes |
|--------|--------|
| `files(activity)` | File-group metadata |
| `file_bytes(file_or_url_or_activity)` | Download into memory (small CSV / spectra) |
| `file_stream(file_or_url)` | Streaming `Response` |
| `download(file_or_url, dest)` | Write to disk |
| `upload_file(activity, source, *, filename=None, description=None)` | Path, bytes, or file-like |
| `upload_activity_file` / `delete_activity_file` | Lower-level variants |

### Data packages

| Method | Notes |
|--------|--------|
| `get_data_package(id_or_doi)` | |
| `find_data_packages(**criteria)` | Auto-paged search; camelCase criteria from Swagger |

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
```

---

## MCP server (optional)

```bash
pip install "listapi[mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
listapi-mcp
# or: python -m listapi.mcp_server
```

Signs in once at process start (`sign_in()`), then exposes read tools: `find_samples`, `sample_stats`, `get_sample`, `activities`, `files`, `file_bytes`, `find_data_packages`, `api_get`. Logs go to **stderr** only.

Cursor / Claude Desktop example:

```json
{
  "mcpServers": {
    "listapi": {
      "command": "listapi-mcp",
      "env": {
        "LIST_URL": "https://list.2dccmip.org/list/dotnet",
        "LIST_API_KEY": "your-key"
      }
    }
  }
}
```

Omit `LIST_API_KEY` to use Entra at startup (`LIST_ENTRA_MODE=device` if no browser).
