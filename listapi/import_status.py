"""LiST sample-import DB status codes (SampleImportTask.Status*)."""

from __future__ import annotations

STATUS_INCOMPLETE = "I"
STATUS_ERROR = "E"
STATUS_NOTHING_TO_DO = "X"
STATUS_CREATED = "C"
STATUS_UPDATED = "U"
STATUS_PENDING = "P"
STATUS_CONFLICT = "M"  # LiST StatusManuallyChanged — researcher review / could not overwrite

IMPORT_STATUS_DESCRIPTIONS: dict[str, str] = {
    STATUS_INCOMPLETE: "incomplete",
    STATUS_ERROR: "error",
    STATUS_CREATED: "recipe imported",
    STATUS_UPDATED: "sample import updated",
    STATUS_NOTHING_TO_DO: "nothing to do",
    STATUS_PENDING: "pending",
    STATUS_CONFLICT: "conflict — manual review",
}

# Default run: incomplete + errors (retry errors is normal).
DEFAULT_IMPORT_STATUSES = frozenset({STATUS_INCOMPLETE, STATUS_ERROR})

# --force: re-process regardless (includes prior conflicts).
FORCE_IMPORT_STATUSES = frozenset(
    {
        STATUS_INCOMPLETE,
        STATUS_ERROR,
        STATUS_NOTHING_TO_DO,
        STATUS_CREATED,
        STATUS_UPDATED,
        STATUS_PENDING,
        STATUS_CONFLICT,
    }
)

# Optional API filterStatus presets (SampleImportFilterStatusDto).
FILTER_ALL = "all"
FILTER_INCOMPLETE = "incomplete"
FILTER_OK = "ok"
FILTER_ANY_ISSUE = "anyIssue"
FILTER_ERROR = "error"


def describe_import_status(status: str) -> str:
    """Short label for sample-import status code (I, C, E, …)."""
    return IMPORT_STATUS_DESCRIPTIONS.get((status or "").upper(), "unknown status")
