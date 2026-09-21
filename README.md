# listapi — Python client for the LiST REST API

Sign in once (API key or Microsoft account), then fetch samples, activities, and files, or create samples / upload results.

## Setup

```bash
cd list-python
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy config\list.py.example config\list.py   # Windows
# cp config/list.py.example config/list.py   # Unix
```

Activate the venv in each new terminal before running scripts.

Edit `config/list.py` — use the same base URL as in your browser, and add /dotnet:

```python
url = "https://your-list-host/dotnet"
api_key = None  # API key string, or None to sign in with a browser
```

Use **`None`** (not `""`) when the API key is unset. Optional overrides: `LIST_CONFIG_DIR`, `LIST_URL`, `LIST_API_KEY`.

**API key:** In the LiST web app, open **About → FAQ**. The support entry shows the data manager for that instance — ask them for a key.

## Sign in

```python
from listapi import sign_in, ListApiError

client = sign_in()  # API key from config, or browser sign-in
sample = client.get_sample("MBE2.123")
```

| Mode | When |
|------|------|
| **API key** | Set `api_key` in config (or `LIST_API_KEY`). Best for scripts and unattended runs. |
| **Browser** | Leave `api_key = None`. A browser window opens; sign in with your usual LiST account. Token is cached under `~/.list/`. For SSH / no browser: `sign_in(entra="device")` or `LIST_ENTRA_MODE=device`. |

Default API version is **v2**. Failures raise `ListApiError` (catch 401 / 403 / 404 in scripts to avoid a traceback). After sign-in, `client.jwt` is available when a JWT was obtained; auth is applied automatically on every call.

## Arbitrary API calls

Helpers cover common flows; anything else on Swagger works through the same authenticated client:

```python
client = sign_in()

projects = client.get("projects")                    # → GET /api/v2/projects
notes = client.get(f"samples/{label}/notes")
client.post("samples/add-to-inventory", json={...})

# Full URL if needed
client.request("GET", "https://host/dotnet/api/v2/…")

# Pass the JWT to another tool
headers = {"Authorization": f"Bearer {client.jwt}"}
```

`get` / `post` / `put` / `patch` / `delete` / `request` raise `ListApiError` on failure and return parsed JSON when the response is JSON. Paths and bodies: `{url}/swagger` in the browser.

## Find samples

`find_samples` wraps `POST /api/v2/samples/search` and **auto-pages** until all matching rows are returned.

Synthesis and characterization filters are independent — you can require both at once:

```python
# Grown on MBE2 since 2026-01-01
rows = client.find_samples(
    syn_instrument="MBE2",
    grown_after="2026-01-01",
)

# Has XRD characterization
rows = client.find_samples(
    char_instrument="XRD1",
    char_technique="XRD",
)

# Grown on MBE2 *and* has XRD available
rows = client.find_samples(
    syn_instrument="MBE2",
    char_technique="XRD",
    grown_after="2026-01-01",
)

# By materials / chemistry (OR within each list — sample must match at least one)
rows = client.find_samples(materials=[12, 34])           # catalog material ids
rows = client.find_samples(material_names=["WSe2", "MoS2"])
rows = client.find_samples(elements=["W", "Se"])         # materials containing those elements

# Exact label
rows = client.find_samples(sample_id="MBE2.123")
# same: label="MBE2.123"
```

| Argument | Notes |
|----------|--------|
| `syn_instrument` / `syn_technique` | Synthesis instrument / technique |
| `char_instrument` / `char_technique` | Has a characterization activity on this instrument / technique |
| `materials` | Catalog material **ids** (ints); sample must include at least one |
| `material_names` | Material **names**; prefer when you do not know ids |
| `elements` | Element symbols (e.g. `W`, `Se`); used when `materials` is empty |
| `grown_after` / `grown_before` | ISO dates |
| `sample_id` / `label` | Exact sample label |
| other `**kwargs` | Same camelCase names as in Swagger (`SampleSearchCriteria`) |

```bash
python examples/find_samples.py --syn-instrument MBE2 --grown-after 2026-01-01
python examples/find_samples.py --char-instrument XRD1 --char-technique XRD
python examples/find_samples.py --syn-instrument MBE2 --char-technique XRD
```

More filters (project, shipping, research group, substrate, …): open `{url}/swagger`, find **`POST /api/v2/samples/search`** → **`SampleSearchCriteria`**, and pass those field names as kwargs:

```python
rows = client.find_samples(
    syn_instrument="MBE2",
    projectId="42",
    addedAfter="2025-01-01",
)
```

Data packages: `find_data_packages(**criteria)` — same idea; see Swagger for `DataPackageSearchCriteria`.

## Activities and files

```python
acts = client.activities(
    sample,                 # label, id, or get_sample() dict
    kind="char",            # syn | char | split
    instrument="RAMAN1",
    technique="RAMAN",
    date="2026-09-21",
)
groups = client.files(acts[0])       # metadata
raw = client.file_bytes(acts[0])     # bytes in memory (e.g. for pandas)
# client.download(file, dest="./out.csv")  # only if you want a path on disk
client.upload_file(acts[0], "./peaks.csv")
```

## Create sample / activity

```python
sample = client.create_sample(researcher_key="…", date="2026-09-21")
act = client.add_activity(sample, kind="char", date="2026-09-21", instrument="RAMAN1", technique="RAMAN")
client.upload_file(act, peaks_bytes, filename="peaks.csv")
```

## Examples

```bash
python examples/sample_metadata.py SAMPLE_ID
python examples/find_samples.py --syn-instrument MBE2 --grown-after 2026-01-01
python examples/analyze_sample.py SAMPLE_ID --date 2026-09-21
python examples/pipeline_create.py   # create sample + upload
```

## Method overview

| Method | Purpose |
|--------|---------|
| `get` / `post` / `put` / `patch` / `delete` / `request` | Any LiST route (auth included) |
| `get_sample` / `find_samples` | One sample, or paged search |
| `get_data_package` / `find_data_packages` | Data packages |
| `activities` / `add_activity` | List or create syn/char (filter by kind / instrument / technique / date) |
| `files` / `file_bytes` / `file_stream` / `download` | Metadata and content |
| `upload_file` | Attach a file to an activity |
| `create_sample` | Add to inventory |
