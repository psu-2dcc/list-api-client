"""Resolve sample / activity / file ids from ints, labels, or API dicts."""

from __future__ import annotations

from typing import Any


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def sample_ref(sample: int | str | dict[str, Any]) -> str:
    """Path segment for /samples/{idOrLabel}."""
    if isinstance(sample, dict):
        label = _first(
            sample.get("sampleLabel"),
            sample.get("SampleLabel"),
            sample.get("sampleId"),
            sample.get("SampleId"),
            sample.get("id"),
            sample.get("ID"),
        )
        if label is None:
            raise ValueError("Sample dict has no sampleLabel or id")
        return str(label)
    return str(sample)


def activity_id(activity: int | str | dict[str, Any]) -> int:
    if isinstance(activity, dict):
        raw = _first(activity.get("id"), activity.get("ID"))
        if raw is None:
            raise ValueError("Activity dict has no id")
        return int(raw)
    return int(activity)


def sample_numeric_id(sample: int | str | dict[str, Any]) -> int:
    """Numeric sample id for create-activity body (sampleId)."""
    if isinstance(sample, dict):
        raw = _first(sample.get("id"), sample.get("ID"))
        if raw is None:
            raise ValueError("Sample dict has no numeric id (fetch with get_sample first)")
        return int(raw)
    if isinstance(sample, int) or (isinstance(sample, str) and sample.isdigit()):
        return int(sample)
    raise ValueError(
        f"Need numeric sample id for this call; got {sample!r}. Pass get_sample(...) result or an int id."
    )


def file_download_url(file_or_group: dict[str, Any]) -> str:
    """Pick a download URL from a file row or a file-group DTO."""
    url = _first(file_or_group.get("downloadUrl"), file_or_group.get("DownloadUrl"))
    if url:
        return str(url)
    nested = file_or_group.get("files") or file_or_group.get("Files") or []
    if isinstance(nested, list):
        for row in nested:
            if not isinstance(row, dict):
                continue
            url = _first(row.get("downloadUrl"), row.get("DownloadUrl"))
            if url:
                return str(url)
    raise ValueError("No downloadUrl on file metadata")


def file_id(file_meta: dict[str, Any]) -> int | None:
    raw = _first(file_meta.get("id"), file_meta.get("ID"))
    return int(raw) if raw is not None else None
