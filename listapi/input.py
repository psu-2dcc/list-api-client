"""Input queue: Gatekeepers push files with ``list-input/1`` metadata into LiST.

A Gatekeeper API key (no internal API) must call **v2** (``Client.api_version`` default).
``POST input`` stores files in ``.input-queue``; LiST identifies and places them later.
Pushing the same content under the same external key again stores nothing (200);
something new yields 202.

See ``GET input/schema`` and LiST ``docs/todo/input-queue-plan.md``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping, Sequence

#: Metadata document id Gatekeepers send (also ``GET input/schema`` ``$id``).
SCHEMA_V1 = "list-input/1"

# ``kind`` values in metadata (InputItemKind.MetadataName).
KIND_SAMPLE_DEFINITION = "sample-definition"
KIND_SYNTHESIS = "synthesis"
KIND_CHARACTERIZATION = "characterization"
KIND_SIMULATION = "simulation"
KIND_ATTACHMENT = "attachment"

KINDS: frozenset[str] = frozenset(
    {
        KIND_SAMPLE_DEFINITION,
        KIND_SYNTHESIS,
        KIND_CHARACTERIZATION,
        KIND_SIMULATION,
        KIND_ATTACHMENT,
    }
)

KIND_LABELS: dict[str, str] = {
    KIND_SAMPLE_DEFINITION: "Sample definition",
    KIND_SYNTHESIS: "Synthesis",
    KIND_CHARACTERIZATION: "Characterization",
    KIND_SIMULATION: "Simulation",
    KIND_ATTACHMENT: "Attachment",
}

# Status ids on input items (InputItemStatus).
STATUS_RECEIVED = "R"
STATUS_QUEUED = "Q"
STATUS_MOVING = "M"
STATUS_WAITING = "W"
STATUS_FAILED = "F"
STATUS_DONE = "D"
STATUS_DISCARDED = "X"
STATUS_DUPLICATE = "U"

STATUS_LABELS: dict[str, str] = {
    STATUS_RECEIVED: "Received",
    STATUS_QUEUED: "Queued",
    STATUS_MOVING: "Moving",
    STATUS_WAITING: "Waiting",
    STATUS_FAILED: "Failed",
    STATUS_DONE: "Done",
    STATUS_DISCARDED: "Discarded",
    STATUS_DUPLICATE: "Duplicate",
}


def describe_input_status(status: str) -> str:
    """Label for an input-item status id (R, Q, W, …)."""
    return STATUS_LABELS.get((status or "").strip().upper(), "unknown status")


def describe_input_kind(kind: str) -> str:
    """Label for a metadata ``kind`` (or wire id S/Y/C/M/A)."""
    text = (kind or "").strip()
    if text in KIND_LABELS:
        return KIND_LABELS[text]
    by_id = {
        "S": KIND_SAMPLE_DEFINITION,
        "Y": KIND_SYNTHESIS,
        "C": KIND_CHARACTERIZATION,
        "M": KIND_SIMULATION,
        "A": KIND_ATTACHMENT,
    }
    mapped = by_id.get(text.upper())
    if mapped:
        return KIND_LABELS[mapped]
    return "unknown kind"


def file_sha256(source: str | Path | bytes | BinaryIO) -> str:
    """SHA-256 hex digest of file bytes (for optional ``files[].sha256`` in metadata)."""
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    if hasattr(source, "read"):
        data = source.read()  # type: ignore[union-attr]
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


@dataclass
class InputFileEntry:
    """One entry of ``files[]`` in ``list-input/1`` (overrides request-level values for that name)."""

    name: str
    sha256: str | None = None
    external_key: str | None = None
    kind: str | None = None
    fields: Mapping[str, str] | None = None

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {"name": self.name}
        if self.sha256 is not None:
            body["sha256"] = self.sha256
        if self.external_key is not None:
            body["externalKey"] = self.external_key
        if self.kind is not None:
            body["kind"] = self.kind
        if self.fields is not None:
            body["fields"] = dict(self.fields)
        return body


@dataclass
class InputMetadata:
    """``list-input/1`` document Gatekeepers send with ``POST input``.

    Every field is optional on the wire; LiST may fill gaps from path rules. Unknown
    ``kind`` values are refused (400). ``schema`` defaults to :data:`SCHEMA_V1` when
    serializing.
    """

    external_key: str | None = None
    kind: str | None = None
    instrument: str | None = None
    sample: str | None = None
    characterization_id: str | None = None
    activity_id: int | None = None
    user: str | None = None
    project: str | None = None
    material: str | None = None
    run: Mapping[str, Any] | None = None
    acquired_at: datetime | str | None = None
    received_at: datetime | str | None = None
    source: Mapping[str, Any] | None = None
    backfill: bool | None = None
    description: str | None = None
    fields: Mapping[str, str] | None = None
    provenance: Mapping[str, Any] | None = None
    files: Sequence[InputFileEntry | Mapping[str, Any]] | None = None
    schema: str = SCHEMA_V1

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {"schema": self.schema or SCHEMA_V1}
        if self.external_key is not None:
            body["externalKey"] = self.external_key
        if self.kind is not None:
            body["kind"] = self.kind
        if self.instrument is not None:
            body["instrument"] = self.instrument
        if self.sample is not None:
            body["sample"] = self.sample
        if self.characterization_id is not None:
            body["characterizationId"] = self.characterization_id
        if self.activity_id is not None:
            body["activityId"] = self.activity_id
        if self.user is not None:
            body["user"] = self.user
        if self.project is not None:
            body["project"] = self.project
        if self.material is not None:
            body["material"] = self.material
        if self.run is not None:
            body["run"] = dict(self.run)
        if self.acquired_at is not None:
            body["acquiredAt"] = _iso_offset(self.acquired_at)
        if self.received_at is not None:
            body["receivedAt"] = _iso_offset(self.received_at)
        if self.source is not None:
            body["source"] = _source_json(self.source)
        if self.backfill is not None:
            body["backfill"] = self.backfill
        if self.description is not None:
            body["description"] = self.description
        if self.fields is not None:
            body["fields"] = dict(self.fields)
        if self.provenance is not None:
            body["provenance"] = dict(self.provenance)
        if self.files is not None:
            body["files"] = [
                f.to_json() if isinstance(f, InputFileEntry) else dict(f) for f in self.files
            ]
        return body

    def to_json_str(self) -> str:
        return json.dumps(self.to_json(), separators=(",", ":"))


@dataclass
class InputPushResult:
    """Result of ``POST input``: one item per file part."""

    submission_id: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    #: True when the server returned 200 (every file already known); False for 202.
    all_existing: bool = False
    status_code: int | None = None

    @classmethod
    def from_response(cls, data: dict[str, Any], status_code: int) -> InputPushResult:
        items = data.get("items") or data.get("Items") or []
        return cls(
            submission_id=data.get("submissionId") or data.get("SubmissionId"),
            items=[row for row in items if isinstance(row, dict)],
            all_existing=status_code == 200,
            status_code=status_code,
        )


def metadata_json(
    metadata: InputMetadata | Mapping[str, Any] | str | None,
) -> str | None:
    """Serialize metadata for the multipart ``metadata`` part."""
    if metadata is None:
        return None
    if isinstance(metadata, str):
        return metadata
    if isinstance(metadata, InputMetadata):
        return metadata.to_json_str()
    body = dict(metadata)
    body.setdefault("schema", SCHEMA_V1)
    return json.dumps(body, default=_json_default, separators=(",", ":"))


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_offset(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _iso_offset(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        # list-input/1 asks for an offset; naive → UTC with Z.
        return value.isoformat() + "Z"
    return value.isoformat()


def _source_json(source: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    path = source.get("path") if "path" in source else source.get("Path")
    modified = (
        source.get("modifiedAt")
        if "modifiedAt" in source
        else source.get("modified_at")
        if "modified_at" in source
        else source.get("ModifiedAt")
    )
    if path is not None:
        out["path"] = str(path)
    if modified is not None:
        out["modifiedAt"] = _iso_offset(modified) if isinstance(modified, datetime) else modified
    for key, value in source.items():
        if key in ("path", "Path", "modifiedAt", "modified_at", "ModifiedAt"):
            continue
        out[key] = value
    return out


def normalize_upload_parts(
    files: Iterable[str | Path | tuple[str, bytes | BinaryIO | str | Path]],
) -> list[tuple[str, bytes]]:
    """Turn paths / ``(filename, content)`` into ``(basename, bytes)`` for multipart ``file`` parts."""
    parts: list[tuple[str, bytes]] = []
    for item in files:
        if isinstance(item, (str, Path)):
            path = Path(item)
            parts.append((path.name, path.read_bytes()))
            continue
        name, content = item
        basename = Path(name).name
        if isinstance(content, Path) or (isinstance(content, str) and Path(content).is_file()):
            parts.append((basename, Path(content).read_bytes()))
        elif isinstance(content, bytes):
            parts.append((basename, content))
        elif isinstance(content, str):
            parts.append((basename, content.encode("utf-8")))
        elif hasattr(content, "read"):
            data = content.read()
            if isinstance(data, str):
                data = data.encode("utf-8")
            parts.append((basename, data))
        else:
            raise TypeError(f"Unsupported file content type: {type(content)!r}")
    if not parts:
        raise ValueError("push_input needs at least one file")
    return parts
