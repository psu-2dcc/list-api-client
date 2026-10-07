# Proposed change: sample notes helpers

**Status:** client methods implemented in `listapi/client.py` (0.5.0), for samples and for sample
activities (`get/save/add/upsert/delete_activity_note*` on `sample-activities/{id}/notes`, same
contract, `ActivityApiController.cs`). MCP tool and tests still open (see Optional).
**Motivation:** `recipe-pipeline` will copy OneNote pages into LiST as sample notes. Right now that
needs raw `client.get(...)` / `client.post(...)` calls. Typed helpers belong here so other tools
(MCP, notebooks) can reuse them.

## Server API (already exists)

Source: `list/server/RestAPI/API/SampleApiController.cs`

| Method | Path | Body / result |
|--------|------|---------------|
| GET    | `/api/v{n}/samples/{idOrLabel}/notes` | → `NoteDto[]`, filtered by what the caller may read |
| POST   | `/api/v{n}/samples/{idOrLabel}/notes` | `NoteDto[]` → the saved `NoteDto[]` |
| DELETE | `/api/v{n}/samples/{idOrLabel}/notes/{noteId}` | → 204 |

`NoteDto` (`server/RestAPI/Dtos/NoteDTO.cs`):

```json
{ "id": null, "title": "…", "text": "<p>HTML…</p>", "visibility": "U",
  "lastChangedDate": "…", "status": "…", "lastChangedByUser": "…" }
```

- `visibility`: `P` (on publication), `U` (user/PI, the default), or `I` (internal).
- The POST is an upsert per item, not a full replace. Items with `id` null or 0 are inserted. Items
  with an existing `id` are updated, and only when the title, text or visibility changed. Notes left
  out of the list are **not** deleted (`NoteRepository.SaveAll`).
- `text` is HTML. The server sanitizes it on save (`NoteMapper.ConvertToEntity` →
  `HTMLSanitizer.SanitizeNote`). That keeps tables, `img[src|style|data-filename]` and inline
  styles, and flattens `div` and `a`. So the stored text can differ from what the client sent. To
  check whether a note changed, compare against the stored note, not the local HTML.

## Proposed client methods (`listapi/client.py`)

```python
def get_sample_notes(self, sample: int | str | dict[str, Any]) -> list[dict[str, Any]]:
    """GET /api/v{n}/samples/{idOrLabel}/notes."""

def save_sample_notes(
    self, sample: int | str | dict[str, Any], notes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """POST /api/v{n}/samples/{idOrLabel}/notes — upsert; returns all readable notes after save."""

def add_sample_note(
    self,
    sample: int | str | dict[str, Any],
    title: str,
    text: str,
    *,
    visibility: Literal["P", "U", "I"] = "U",
) -> dict[str, Any]:
    """Insert one note (id omitted); return the saved note (matched by title, newest lastChangedDate)."""

def upsert_sample_note_by_title(
    self,
    sample: int | str | dict[str, Any],
    title: str,
    text: str,
    *,
    visibility: Literal["P", "U", "I"] = "U",
) -> dict[str, Any]:
    """Update the note with this exact title if it exists, else insert. Makes re-runs idempotent."""

def delete_sample_note(self, sample: int | str | dict[str, Any], note_id: int) -> None:
    """DELETE /api/v{n}/samples/{idOrLabel}/notes/{noteId}."""
```

Use `ids.sample_ref(sample)` for the path segment, the same way `get_sample` does.

`upsert_sample_note_by_title` is the one recipe-pipeline needs. The POST does not return the id of
a new note on its own, so a sync job that runs every day would add duplicates without this helper.

## Optional

- **MCP:** add `sample_notes(sample)` as a read-only tool in `mcp_server.py`.
- **`find_samples`:** document how to filter by several synthesis instruments. Today
  `syn_instrument` takes one id, so MBE1/MBE5/MBE6 means three calls merged by sample id. If
  `SampleSearchCriteria` gains a list field (e.g. `instrumentIds`), expose it as
  `syn_instruments: list[str]`.
- **Tests:** mock the three endpoints. Cover these cases: an upsert that finds an existing title, an
  upsert that inserts, and a 403 surfacing as `ListApiError`.
