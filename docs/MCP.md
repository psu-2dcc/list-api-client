# MCP setup — Cursor & Claude Desktop

[← Main README](../README.md)

Run **listapi** as an MCP server so an AI host can call LiST (search samples, stats, activities, files) through tools. The host launches a local process; it is **not** an HTTP service you browse to.

## What you get

At start the process calls `sign_in()` once (API key from env, or Entra if no key). Then these **read** tools are available:

| Tool | Purpose |
|------|---------|
| `find_samples` | Sample search (result capped by `limit`) |
| `sample_stats` | Aggregated statistics for the same filters |
| `get_sample` | One sample by label or id |
| `activities` | Activities for a sample (`syn` / `char` / `split`) |
| `files` | File metadata for an activity |
| `file_bytes` | File content as base64 (size-capped) |
| `find_data_packages` | Data-package search |
| `api_get` | `GET` any `/api/v2/…` path |

Full library API (scripts, writes, etc.): [README.md](../README.md).

---

## 1. Install into a dedicated venv (from GitHub)

Use a venv just for this MCP so Cursor/Claude always hit the right Python.

**PowerShell (Windows)** — use `$env:USERPROFILE`, not `%USERPROFILE%` (PowerShell does not expand `%…%`):

```powershell
python -m venv "$env:USERPROFILE\.venvs\listapi"
& "$env:USERPROFILE\.venvs\listapi\Scripts\Activate.ps1"
pip install "listapi[mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
# optional pin: ...list-api-client.git@v0.2.0
Get-Command listapi-mcp
```

Typical path:

`C:\Users\<you>\.venvs\listapi\Scripts\listapi-mcp.exe`

**bash / macOS / Linux:**

```bash
python3 -m venv "$HOME/.venvs/listapi"
source "$HOME/.venvs/listapi/bin/activate"
pip install "listapi[mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
which listapi-mcp
```

Typical path: `~/.venvs/listapi/bin/listapi-mcp`

Entra (browser / device code) also needs:

```bash
pip install "listapi[entra,mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
```

---

## 2. Environment

| Variable | Role |
|----------|------|
| `LIST_URL` | LiST base URL (default public: `https://list.2dccmip.org/list/dotnet`) |
| `LIST_API_KEY` | API key (preferred for unattended MCP). Omit for Entra. |
| `LIST_ENTRA_MODE` | `device` if no browser (SSH / headless) |

Get a key: LiST web → **About → FAQ** → ask that instance’s data manager.

Do **not** run `listapi-mcp` by hand expecting a chat UI — it waits on stdin for MCP JSON-RPC. The host starts it for you.

---

## 3. Cursor

1. Open **Cursor Settings → MCP** (or edit the MCP JSON config Cursor uses for your user/project).
2. Add a server entry. Prefer an **absolute path** to the venv executable:

```json
{
  "mcpServers": {
    "listapi": {
      "command": "C:/Users/YOU/.venvs/listapi/Scripts/listapi-mcp.exe",
      "env": {
        "LIST_URL": "https://list.2dccmip.org/list/dotnet",
        "LIST_API_KEY": "your-key"
      }
    }
  }
}
```

macOS / Linux:

```json
{
  "mcpServers": {
    "listapi": {
      "command": "/Users/YOU/.venvs/listapi/bin/listapi-mcp",
      "env": {
        "LIST_URL": "https://list.2dccmip.org/list/dotnet",
        "LIST_API_KEY": "your-key"
      }
    }
  }
}
```

Alternative (same venv’s Python):

```json
"command": "C:/Users/YOU/.venvs/listapi/Scripts/python.exe",
"args": ["-m", "listapi.mcp_server"]
```

3. Save and **reload / restart MCP** (or restart Cursor).
4. Confirm the `listapi` server shows as connected; tools should appear for the agent.

---

## 4. Claude Desktop

1. Edit Claude’s config file:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

2. Same `mcpServers` shape as Cursor:

```json
{
  "mcpServers": {
    "listapi": {
      "command": "C:/Users/YOU/.venvs/listapi/Scripts/listapi-mcp.exe",
      "env": {
        "LIST_URL": "https://list.2dccmip.org/list/dotnet",
        "LIST_API_KEY": "your-key"
      }
    }
  }
}
```

On macOS use the `bin/listapi-mcp` path under `~/.venvs/listapi`.

3. **Fully quit and reopen** Claude Desktop so it relaunches MCP processes.

---

## 5. Entra instead of an API key

Omit `LIST_API_KEY` from `env`. On first start the process may open a browser or print a device code (stderr). Install `listapi[entra,mcp]`. For no browser:

```json
"env": {
  "LIST_URL": "https://list.2dccmip.org/list/dotnet",
  "LIST_ENTRA_MODE": "device"
}
```

MSAL cache: `~/.list/msal_cache.bin`.

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Server fails to start | Absolute `command` path; venv has `listapi[mcp]`; `Get-Command listapi-mcp` / `which listapi-mcp` |
| 401 / sign-in failed | `LIST_URL` + `LIST_API_KEY`, or Entra extras installed |
| Wrong / missing tools | Reload MCP; ensure you’re not pointing at an old install |
| Accidental `%USERPROFILE%` folder under the repo | PowerShell literal — delete it and recreate the venv with `$env:USERPROFILE` |

Upgrade later:

```powershell
& "$env:USERPROFILE\.venvs\listapi\Scripts\Activate.ps1"
pip install -U "listapi[mcp] @ git+https://github.com/psu-2dcc/list-api-client.git"
```
