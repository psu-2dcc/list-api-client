"""Input queue: Gatekeepers push files with ``list-input/1`` metadata into LiST.

Use it through ``client.input``::

    client = sign_in(url, api_key=gatekeeper_key)
    result = client.input.push([("MBE2-run1.rcp", "recipe")], metadata={"instrument": "MBE2"})

A Gatekeeper's API key is sent on every call (``X-API-Key``) and never exchanged for a JWT; it
works on **api/v2** only, and only for its own instruments. ``push`` stores the files in the
queue; LiST identifies and places them afterwards. The client never decides synthesis vs.
characterization and never reads a recipe or data file: it only tells LiST each file's
:data:`role`.

Item statuses (``status`` of an item): ``R`` received, ``Q`` queued, ``M`` moving, ``W`` waiting
(may fix itself), ``F`` failed (needs a correction), ``D`` done, ``X`` discarded, ``U`` duplicate.

Error codes a sender may see on an item: LiST retries on its own for :data:`WAITING_ERROR_CODES`
(``SampleNotFound``, ``SampleUnresolved``, ``RunNotFound``, ``InstrumentUnknown``); a person has to
act for :data:`NEEDS_PERSON_ERROR_CODES` (``KindUnknown``, ``RoleUnknown``, ``InstrumentAmbiguous``,
``InvalidFormat``, ``NotAllowed``).
"""

from __future__ import annotations

import fnmatch
import json
import logging
import mimetypes
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Iterable, Mapping, Sequence

import requests

from listapi._multipart import Source, build
from listapi.errors import FeatureNotSupported, RoleUnknown

if TYPE_CHECKING:  # pragma: no cover
    from listapi.client import Client

logger = logging.getLogger(__name__)

#: Metadata document id Gatekeepers send (also ``GET input/schema`` ``$id``).
SCHEMA_V1 = "list-input/1"

# -- roles (files[].role) ---------------------------------------------------------------------

ROLE_SAMPLE_DEFINITION = "sample-definition"
ROLE_RECIPE = "recipe"
ROLE_LOG = "log"
#: Companion of a log (same base name, e.g. the recorder ``.csv``); lands on the log's activity.
ROLE_DATA = "data"
ROLE_CHARACTERIZATION = "characterization"

ROLES: frozenset[str] = frozenset(
    {ROLE_SAMPLE_DEFINITION, ROLE_RECIPE, ROLE_LOG, ROLE_DATA, ROLE_CHARACTERIZATION}
)

#: Order that helps LiST when one request carries several roles (definition and recipes first).
_ROLE_ORDER = {
    ROLE_SAMPLE_DEFINITION: 0,
    ROLE_RECIPE: 1,
    ROLE_LOG: 2,
    ROLE_DATA: 3,
    ROLE_CHARACTERIZATION: 4,
}

# -- item statuses ----------------------------------------------------------------------------

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

#: Statuses that are still in progress on LiST's side; ``wait`` polls until none is left.
PENDING_STATUSES: frozenset[str] = frozenset({STATUS_RECEIVED, STATUS_QUEUED, STATUS_MOVING})

WAITING_ERROR_CODES: frozenset[str] = frozenset(
    {"SampleNotFound", "SampleUnresolved", "RunNotFound", "InstrumentUnknown"}
)
NEEDS_PERSON_ERROR_CODES: frozenset[str] = frozenset(
    {"KindUnknown", "RoleUnknown", "InstrumentAmbiguous", "InvalidFormat", "NotAllowed"}
)

#: Server limit on one ``exists`` call.
MAX_EXISTS_ITEMS = 500


def describe_input_status(status: str) -> str:
    """Label for an input-item status id (R, Q, W, ...)."""
    return STATUS_LABELS.get((status or "").strip().upper(), "unknown status")


def describe_input_error(code: str | None) -> str:
    """Whether an item error code fixes itself (LiST retries) or needs a person."""
    if code in WAITING_ERROR_CODES:
        return "waiting: LiST retries on its own"
    if code in NEEDS_PERSON_ERROR_CODES:
        return "needs a person (correction)"
    return "unknown error code" if code else ""


def check_role(role: str | None) -> str | None:
    """Return ``role`` if it is a known role (or ``None``); raise :class:`RoleUnknown` otherwise."""
    if role is None:
        return None
    if role not in ROLES:
        raise RoleUnknown(
            f"Unknown role {role!r}; expected one of: {', '.join(sorted(ROLES))}",
        )
    return role


def file_sha256(source: str | Path | bytes | BinaryIO) -> str:
    """SHA-256 hex digest of a file, read in chunks (a multi-GB file is never held in memory)."""
    if isinstance(source, (str, Path)):
        return Source.of(Path(source).name, Path(source)).sha256()
    if isinstance(source, (bytes, bytearray)):
        return Source.of("", bytes(source)).sha256()
    return Source.of("", source).sha256()


# -- metadata (list-input/1) --------------------------------------------------------------------


def _iso_offset(value: datetime | date | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        # A naive time is read by the server as *its* local time; send it unchanged.
        return value.isoformat()
    return value.isoformat()


def _clean(value: Any) -> Any:
    """Drop ``None``, ``""`` and empty containers recursively (never send ``""``)."""
    if isinstance(value, Mapping):
        out = {str(k): _clean(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if not _is_absent(v)}
    if isinstance(value, (list, tuple)):
        return [v for v in (_clean(x) for x in value) if not _is_absent(v)]
    if isinstance(value, (datetime, date)):
        return _iso_offset(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_json"):
        return _clean(value.to_json())
    return value


def _is_absent(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, (dict, list)) and not value)


@dataclass
class InputRun:
    """``run``: which synthesis run (``key``, ``index`` or ``start``), or the measurement key for characterization."""

    key: str | None = None
    index: int | None = None
    start: datetime | str | None = None
    material: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _clean(
            {"key": self.key, "index": self.index, "start": self.start, "material": self.material}
        )


@dataclass
class InputSource:
    """``source``: where the file was on the instrument PC."""

    path: str | Path | None = None
    modified_at: datetime | str | None = None

    def to_json(self) -> dict[str, Any]:
        return _clean({"path": self.path, "modifiedAt": self.modified_at})


@dataclass
class InputFileEntry:
    """One entry of ``files[]``. Today the server reads ``role``, ``name``, ``sha256``, ``externalKey``, ``fields``."""

    name: str
    sha256: str | None = None
    external_key: str | None = None
    role: str | None = None
    fields: Mapping[str, str] | None = None

    def to_json(self) -> dict[str, Any]:
        return _clean(
            {
                "name": self.name,
                "sha256": self.sha256,
                "externalKey": self.external_key,
                "role": self.role,
                "fields": self.fields,
            }
        )


@dataclass
class InputMetadata:
    """The ``list-input/1`` document. Every field is optional; absent values are left out of the JSON.

    ``user`` takes an ORCID (bare or ``https://orcid.org/...``) or an EPPN: pass what the operator's
    sign-in gives, do not invent one. Times should carry an offset; a naive time is read as the
    server's local time. There is no request-level ``kind`` (ignored by the server) and no
    ``provenance`` block any more.
    """

    external_key: str | None = None
    instrument: str | None = None
    sample: str | None = None
    user: str | None = None
    project: str | None = None
    acquired_at: datetime | str | None = None
    run: InputRun | Mapping[str, Any] | None = None
    source: InputSource | Mapping[str, Any] | None = None
    description: str | None = None
    fields: Mapping[str, str] | None = None
    files: Sequence[InputFileEntry | Mapping[str, Any]] | None = None
    schema: str = SCHEMA_V1

    def to_json(self) -> dict[str, Any]:
        files = []
        for entry in self.files or ():
            body = entry.to_json() if isinstance(entry, InputFileEntry) else _clean(dict(entry))
            check_role(body.get("role"))
            files.append(body)
        return _clean(
            {
                "schema": self.schema or SCHEMA_V1,
                "externalKey": self.external_key,
                "instrument": self.instrument,
                "sample": self.sample,
                "user": self.user,
                "project": self.project,
                "acquiredAt": self.acquired_at,
                "run": self.run,
                "source": self.source,
                "description": self.description,
                "fields": self.fields,
                "files": files,
            }
        )

    def to_json_str(self) -> str:
        return json.dumps(self.to_json(), separators=(",", ":"))


_DICT_KEYS = {
    "external_key": "externalKey",
    "acquired_at": "acquiredAt",
    "modified_at": "modifiedAt",
}


def _metadata_dict(metadata: InputMetadata | Mapping[str, Any] | str | None) -> dict[str, Any]:
    if metadata is None:
        return {"schema": SCHEMA_V1}
    if isinstance(metadata, str):
        body = json.loads(metadata)
    elif isinstance(metadata, InputMetadata):
        body = metadata.to_json()
    else:
        body = _clean({_DICT_KEYS.get(k, k): v for k, v in metadata.items()})
    if not isinstance(body, dict):
        raise ValueError("metadata must be a JSON object")
    body.setdefault("schema", SCHEMA_V1)
    return body


# -- results --------------------------------------------------------------------------------------


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
        pascal = name[:1].upper() + name[1:]
        if pascal in row:
            return row[pascal]
    return None


@dataclass
class PushedItem:
    """One file of a push, as answered by the server."""

    id: int | None
    file_name: str | None
    status: str | None
    existing: bool = False

    @classmethod
    def from_json(cls, row: Mapping[str, Any]) -> "PushedItem":
        return cls(
            id=_pick(row, "id"),
            file_name=_pick(row, "fileName"),
            status=_pick(row, "status"),
            existing=bool(_pick(row, "existing")),
        )


@dataclass
class PushResult:
    """Result of ``POST input``."""

    submission_id: str | None = None
    items: list[PushedItem] = field(default_factory=list)
    #: ``True`` for 202 (something new was stored); ``False`` for 200 (every file was known already).
    created: bool = True
    status_code: int | None = None

    @property
    def all_existing(self) -> bool:
        return not self.created

    @classmethod
    def from_response(cls, data: Mapping[str, Any], status_code: int) -> "PushResult":
        rows = _pick(data, "items") or []
        return cls(
            submission_id=_pick(data, "submissionId"),
            items=[PushedItem.from_json(r) for r in rows if isinstance(r, Mapping)],
            created=status_code != 200,
            status_code=status_code,
        )


#: Old name.
InputPushResult = PushResult


@dataclass
class ExistsResult:
    """Answer of ``exists`` for one ``externalKey``."""

    external_key: str
    #: Same key and same content already pushed: pushing again stores nothing.
    known: bool
    latest_item_id: int | None = None
    latest_status: str | None = None
    latest_content_hash: str | None = None
    latest_size: int | None = None

    @classmethod
    def from_json(cls, row: Mapping[str, Any]) -> "ExistsResult":
        return cls(
            external_key=_pick(row, "externalKey") or "",
            known=bool(_pick(row, "known")),
            latest_item_id=_pick(row, "latestItemId"),
            latest_status=_pick(row, "latestStatus"),
            latest_content_hash=_pick(row, "latestContentHash"),
            latest_size=_pick(row, "latestSize"),
        )


@dataclass
class ItemState:
    """Status of one queue item, as returned by ``find`` / ``wait``."""

    id: int | None
    file_name: str | None
    status: str | None
    error_code: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def pending(self) -> bool:
        return (self.status or "") in PENDING_STATUSES

    @classmethod
    def from_json(cls, row: Mapping[str, Any]) -> "ItemState":
        return cls(
            id=_pick(row, "id"),
            file_name=_pick(row, "fileName"),
            status=_pick(row, "status"),
            error_code=_pick(row, "errorCode"),
            raw=row,
        )


# -- file arguments -----------------------------------------------------------------------------


@dataclass
class PushFile:
    """One file to push, with everything the multipart body and ``files[]`` need.

    ``source`` is a path, bytes, or a binary file object; ``name`` defaults to the path's basename.
    The shortcuts ``push()`` accepts are: ``path``, ``(path, role)`` and ``(name, content, role)``.
    """

    source: str | Path | bytes | BinaryIO
    role: str | None = None
    name: str | None = None
    external_key: str | None = None
    sha256: str | None = None
    fields: Mapping[str, str] | None = None


def _as_push_file(item: Any) -> PushFile:
    if isinstance(item, PushFile):
        return item
    if isinstance(item, (str, Path)):
        return PushFile(item)
    if isinstance(item, tuple):
        if len(item) == 2 and isinstance(item[1], str):
            return PushFile(item[0], role=item[1])
        if len(item) == 2:
            return PushFile(item[1], name=item[0])
        if len(item) == 3:
            name, content, role = item
            return PushFile(content, role=role, name=name)
    raise TypeError(
        "files must be paths, (path, role), (name, content, role) tuples or PushFile objects"
    )


def _guess_mime(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def default_external_key(instrument: str, role: str, name: str, run_key: str | None = None) -> str:
    """The convention: ``{instrument}/{role}/{fileName}``, or with a run
    ``{instrument}/{run key}/{role}/{fileName}`` so a name that repeats per run does not replace
    the earlier run's file (same key + new content replaces).
    """
    if run_key:
        return f"{instrument}/{run_key}/{role}/{name}"
    return f"{instrument}/{role}/{name}"


# -- the namespace ------------------------------------------------------------------------------


class InputNamespace:
    """``client.input``: push files into the LiST input queue and follow them."""

    #: HTTP status codes worth retrying (with backoff); 4xx are final.
    RETRY_STATUSES = frozenset({500, 502, 503, 504})

    def __init__(
        self,
        client: "Client",
        *,
        timeout: float | tuple[float, float] = (30, 1800),
        retries: int = 4,
        backoff: float = 2.0,
    ) -> None:
        self._client = client
        #: ``requests`` timeout for push: (connect, read) seconds. Generous for multi-GB uploads.
        self.timeout = timeout
        #: Attempts after the first, for network errors and 5xx.
        self.retries = retries
        #: First backoff delay in seconds (doubles each attempt).
        self.backoff = backoff
        #: Probe the server once (``GET input/schema``) and refuse early on a build without the queue.
        self.check_server = True
        self._supported: bool | None = None

    # -- server support ---------------------------------------------------------------------

    def supported(self) -> bool | None:
        """Does this server build have the input queue? Probes ``GET input/schema`` once and caches it.

        ``True``: the build has it (the queue can still be switched off in its config; a push then
        answers 404 "The input queue is off"). ``False``: the build has no input API (404). ``None``:
        could not tell (network error, other status); calls are then attempted anyway.
        """
        if self._supported is None:
            try:
                resp = self._client._request("GET", self._client._api("input/schema"), timeout=30)
            except requests.RequestException:
                return None
            if resp.status_code == 200:
                self._supported = True
            elif resp.status_code == 404:
                self._supported = False
            else:
                return None
        return self._supported

    def _require(self) -> None:
        if not self.check_server or self.supported() is not False:
            return
        try:
            info = self._client.server_info()
        except Exception:  # the message is only richer with it
            info = {}
        build = ""
        if info.get("branch") or info.get("commitHash"):
            build = (
                f" ({info.get('branch') or '?'} @ {info.get('commitHash') or '?'}"
                f", built {info.get('buildDate') or '?'})"
            )
        raise FeatureNotSupported(
            f"This LiST server{build} has no input queue (GET api/v{self._client.api_version}/input/schema "
            "answered 404). It needs a build with the input queue.",
            server=info,
        )

    # -- push -----------------------------------------------------------------------------------

    def push(
        self,
        files: Iterable[Any],
        metadata: InputMetadata | Mapping[str, Any] | str | None = None,
        *,
        external_keys: bool = True,
    ) -> PushResult:
        """``POST input``: one request, one ``submissionId``, files placed in the order given.

        ``files``: paths, ``(path, role)``, ``(name, content, role)`` or :class:`PushFile`. Put the
        files that belong together (definition, recipes, log, csv) into one call; put the definition
        or recipe first. For each file ``push`` computes the sha256 (the server refuses the whole
        request on a mismatch, so a broken upload is detected, not stored) and streams the body
        from disk. With ``external_keys`` (default) a file without a key gets
        ``{instrument}/{role}/{fileName}`` (``{instrument}/{run.key}/{role}/{fileName}`` when the
        metadata has a ``run.key``) when the metadata names an instrument and the file a role; the same key with the same content is a no-op (200, ``created`` is ``False``), the
        same key with new content replaces. Pass your own ``externalKey`` per file (or a
        request-level one) when a name repeats, e.g. per run: ``MBE2/2026-10-28/run1/growth.log``.

        Network errors and 5xx are retried with backoff; thanks to idempotency a retry of a
        request that had succeeded answers 200. Raises :class:`~listapi.errors.RoleUnknown` before
        any request for an unknown role, and :class:`~listapi.errors.ListApiError` subclasses for
        400 / 403 / 404 / 413 (``status_code`` and the server's ``detail`` are kept).
        """
        specs = [_as_push_file(f) for f in files]
        if not specs:
            raise ValueError("push needs at least one file")
        meta = _metadata_dict(metadata)
        for spec in specs:
            check_role(spec.role)
        for entry in meta.get("files") or []:
            check_role(entry.get("role") if isinstance(entry, dict) else None)
        self._require()  # after the local checks, before reading any file
        provided = {e.get("name"): e for e in meta.get("files") or [] if isinstance(e, dict)}
        instrument = meta.get("instrument")
        request_key = meta.get("externalKey")

        sources: list[tuple[Source, str]] = []
        entries: list[dict[str, Any]] = []
        for spec in specs:
            name = spec.name or _name_of(spec.source)
            entry_in = provided.get(name, {})
            role = check_role(spec.role or entry_in.get("role"))
            src = Source.of(name, Path(spec.source) if isinstance(spec.source, (str, Path)) else spec.source)
            entry: dict[str, Any] = dict(entry_in)
            entry["name"] = name
            entry["sha256"] = spec.sha256 or entry_in.get("sha256") or src.sha256()
            key = spec.external_key or entry_in.get("externalKey")
            if key is None and external_keys and instrument and role and not request_key:
                key = default_external_key(instrument, role, name, (meta.get("run") or {}).get("key"))
            if key:
                entry["externalKey"] = key
            if role:
                entry["role"] = role
            if spec.fields:
                entry["fields"] = dict(spec.fields)
            entries.append(_clean(entry))
            sources.append((src, _guess_mime(name)))
        meta["files"] = entries
        body_factory = build(json.dumps(_clean(meta), separators=(",", ":")), sources)

        def send() -> requests.Response:
            body = body_factory()
            try:
                return self._client._request(
                    "POST",
                    self._client._api("input"),
                    data=body,
                    headers={"Content-Type": body.content_type},
                    timeout=self.timeout,
                )
            finally:
                body.close()

        resp = self._with_retries(send, "POST input")
        self._client._raise(resp, "POST input")
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object from POST input, got {type(payload)}")
        return PushResult.from_response(payload, resp.status_code)

    def push_folder(
        self,
        path: str | Path,
        instrument: str,
        role_by_glob: Mapping[str, str] | None = None,
        *,
        metadata: InputMetadata | Mapping[str, Any] | None = None,
        key_template: str = "{instrument}/{role}/{name}",
        skip_known: bool = True,
    ) -> PushResult:
        """Push the files of one folder (not recursive) as **one** request.

        ``role_by_glob`` maps a filename pattern to a role (default ``*.rcp`` recipe, ``*.log`` log,
        ``*.csv`` data; the first matching pattern wins, files that match nothing are skipped).
        Files are ordered definition, recipe, log, data. The key of each file is
        ``key_template`` (fields ``instrument``, ``role``, ``name``, ``folder``). With
        ``skip_known`` one :meth:`exists` call drops the files LiST already holds with that content.
        Returns a ``created=False`` result with no items when nothing was left to push.
        """
        folder = Path(path)
        if not folder.is_dir():
            raise NotADirectoryError(str(folder))
        globs = dict(
            role_by_glob
            if role_by_glob is not None
            else {"*.rcp": ROLE_RECIPE, "*.log": ROLE_LOG, "*.csv": ROLE_DATA}
        )
        for role in globs.values():
            check_role(role)
        picked: list[PushFile] = []
        for file in sorted(p for p in folder.iterdir() if p.is_file()):
            role = next((r for pat, r in globs.items() if fnmatch.fnmatch(file.name, pat)), None)
            if role is None:
                continue
            key = key_template.format(
                instrument=instrument, role=role, name=file.name, folder=folder.name
            )
            picked.append(PushFile(file, role=role, external_key=key, sha256=file_sha256(file)))
        picked.sort(key=lambda f: _ROLE_ORDER.get(f.role or "", 99))
        if skip_known and picked:
            known = {
                r.external_key
                for r in self.exists(
                    [{"externalKey": f.external_key, "sha256": f.sha256} for f in picked]
                )
                if r.known
            }
            picked = [f for f in picked if f.external_key not in known]
        if not picked:
            return PushResult(submission_id=None, items=[], created=False)
        meta = _metadata_dict(metadata)
        meta["instrument"] = instrument
        return self.push(picked, meta, external_keys=False)

    # -- the read side --------------------------------------------------------------------------

    def exists(self, items: Iterable[Mapping[str, str] | tuple[str, str]]) -> list[ExistsResult]:
        """``POST input/exists``: is this ``externalKey`` + ``sha256`` already pushed?

        ``items`` are ``{"externalKey": ..., "sha256": ...}`` dicts or ``(key, sha256)`` tuples; more
        than 500 are split into several calls. ``known`` means pushing again stores nothing, so
        use it before re-sending gigabytes after a local record was lost.
        """
        rows = [
            {"externalKey": i[0], "sha256": i[1]} if isinstance(i, tuple) else dict(i)
            for i in items
        ]
        out: list[ExistsResult] = []
        for start in range(0, len(rows), MAX_EXISTS_ITEMS):
            chunk = rows[start : start + MAX_EXISTS_ITEMS]
            data = self._call("POST", "input/exists", json={"items": chunk})
            found = data.get("items") or data.get("Items") if isinstance(data, dict) else data
            out.extend(ExistsResult.from_json(r) for r in found or [] if isinstance(r, Mapping))
        return out

    def status(self) -> dict[str, Any]:
        """``GET input/ingest-status``: ``count``, ``latestReceived``, ``countByStatus`` (the sender's bookmark)."""
        return self._expect(self._call("GET", "input/ingest-status"), dict, "status")

    def get(self, item_id: int) -> dict[str, Any]:
        """``GET input/{id}``: item with metadata, corrections and steps (own items only)."""
        return self._expect(self._call("GET", f"input/{int(item_id)}"), dict, "get")

    def find(
        self, submission_id: str | None = None, external_key: str | None = None
    ) -> list[dict[str, Any]]:
        """``GET input?submissionId=|externalKey=``: newest first, at most 500. Give one of the two."""
        if (submission_id is None) == (external_key is None):
            raise ValueError("Give exactly one of submission_id or external_key")
        params = (
            {"submissionId": submission_id}
            if submission_id is not None
            else {"externalKey": external_key}
        )
        data = self._expect(self._call("GET", "input", params=params), list, "find")
        return [row for row in data if isinstance(row, dict)]

    def schema(self) -> dict[str, Any]:
        """``GET input/schema``: JSON Schema of ``list-input/1`` (from the server's ``InputMetadata``)."""
        return self._expect(self._call("GET", "input/schema"), dict, "schema")

    def wait(
        self, submission_id: str, timeout: float = 300, *, interval: float = 2.0
    ) -> list[ItemState]:
        """Poll :meth:`find` until no item of the submission is received/queued/moving.

        Returns the final states: ``D`` done, ``W`` waiting (with ``error_code``), ``F`` failed.
        Handy in tests and scripts; a Gatekeeper need not wait (the push itself already succeeded).
        Raises :class:`TimeoutError` (with the last states in ``.items``) after ``timeout`` seconds.
        """
        deadline = time.monotonic() + timeout
        while True:
            states = [ItemState.from_json(r) for r in self.find(submission_id=submission_id)]
            if states and not any(s.pending for s in states):
                return states
            if time.monotonic() >= deadline:
                err = TimeoutError(f"Submission {submission_id} still in progress after {timeout}s")
                err.items = states  # type: ignore[attr-defined]
                raise err
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    # -- plumbing -------------------------------------------------------------------------------

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        if path != "input/schema":
            self._require()
        timeout = kwargs.pop("timeout", 120)

        def send() -> requests.Response:
            return self._client._request(
                method, self._client._api(path), timeout=timeout, **kwargs
            )

        resp = self._with_retries(send, f"{method} {path}")
        self._client._raise(resp, f"{method} {path}")
        return resp.json() if resp.content else None

    def _with_retries(self, send: Any, what: str) -> requests.Response:
        delay = self.backoff
        for attempt in range(self.retries + 1):
            last = attempt == self.retries
            try:
                resp = send()
            except (requests.ConnectionError, requests.Timeout) as exc:
                if last:
                    raise
                logger.warning("%s: %s; retrying in %.1fs", what, exc, delay)
            else:
                if resp.status_code not in self.RETRY_STATUSES or last:
                    return resp
                logger.warning("%s: HTTP %s; retrying in %.1fs", what, resp.status_code, delay)
            time.sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")

    @staticmethod
    def _expect(data: Any, kind: type, what: str) -> Any:
        if not isinstance(data, kind):
            raise ValueError(f"Expected {kind.__name__} from input.{what}, got {type(data)}")
        return data


def _name_of(source: Any) -> str:
    if isinstance(source, (str, Path)):
        return Path(source).name
    name = getattr(source, "name", None)
    if isinstance(name, str):
        return Path(name).name
    raise ValueError("A file given as bytes or a stream needs a name: use (name, content, role) or PushFile")
