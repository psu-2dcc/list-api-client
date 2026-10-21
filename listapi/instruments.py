"""Instrument history: push events from an instrument-side script.

A script at the instrument reads its event log (or log files) and pushes the events to LiST. Every event carries
an ``external_key``: the instrument system's id for it, or a stable hash of the log entry (:func:`stable_key`).
LiST creates or updates events by that key, so pushing the same log again is safe; there is nothing to remember
locally (:meth:`listapi.Client.instrument_ingest_status` tells what was pushed).

Authentication: a role-based API key that lists the instrument (API key dialog, "Instrument history"; admins set
it up) and whose role has the privilege InstrumentHistory. Needs a LiST server with instrument history ingest
(``PUT synthesis-instruments/{id}/events``); production LiST does not have it yet.

Example::

    from datetime import datetime, timedelta, timezone
    from listapi import sign_in_api_key
    from listapi.instruments import InstrumentEvent, stable_key

    client = sign_in_api_key("https://list.example.org", api_key)
    start = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    event = InstrumentEvent(
        external_key=stable_key("bakeout", start.isoformat()),
        event_type="BAKE",
        start=start,
        end=start + timedelta(hours=36),
        title="Bakeout after cell refill",
        description="<p>Cells 3 and 5 refilled.</p>",
    )
    result = client.push_instrument_events("MBE2", [event])
    print(result.created, result.updated, result.unchanged)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from listapi.errors import ListApiError

#: LiST accepts at most this many events per push; :meth:`Client.push_instrument_events` splits larger lists.
MAX_EVENTS_PER_PUSH = 1000

#: Longest external key LiST stores.
MAX_EXTERNAL_KEY_LENGTH = 200


@dataclass
class InstrumentEvent:
    """One event to push.

    ``event_type`` is an event type ID as defined in LiST (Customizing → Instrument event types), e.g. ``MAINT``,
    ``CLEAN``, ``BAKE``, ``CALIB``, ``OTHER``. Give ``end`` or ``duration_hours`` (``end`` wins), or neither for a
    point in time. Naive datetimes are taken as UTC. ``description`` is HTML (LiST sanitizes it like notes);
    ``None`` for none.
    """

    external_key: str
    event_type: str
    start: datetime
    title: str
    end: datetime | None = None
    duration_hours: float | None = None
    description: str | None = None

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "externalKey": self.external_key,
            "eventTypeID": self.event_type,
            "start": _iso(self.start),
            "title": self.title,
        }
        if self.end is not None:
            body["end"] = _iso(self.end)
        elif self.duration_hours is not None:
            body["durationHours"] = self.duration_hours
        if self.description is not None:
            body["description"] = self.description
        return body


@dataclass
class InstrumentPushResult:
    """What a push did, summed over all batches. ``results`` per event in push order (``index``,
    ``externalKey``, ``status`` = Created / Updated / Unchanged, ``eventId``)."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


class InstrumentPushError(ListApiError):
    """A push LiST refused (422): nothing of that batch was saved.

    ``errors`` lists every invalid item: ``index`` (position in the list given to the push call), ``externalKey``
    and ``message``.
    """

    def __init__(self, message: str, errors: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.errors = errors

    def __str__(self) -> str:
        lines = [super().__str__()]
        lines += [f"  #{e.get('index')} {e.get('externalKey') or ''}: {e.get('message')}" for e in self.errors]
        return "\n".join(lines)


def stable_key(*parts: Any, prefix: str | None = None) -> str:
    """A stable external key from the parts that identify a log entry (e.g. type and start time).

    The same parts always give the same key, so re-reading a log updates instead of duplicating. Use the
    instrument system's own event id instead when there is one. ``prefix`` (e.g. the log's name) keeps keys of
    different sources apart and readable.
    """
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]
    key = f"{prefix}:{digest}" if prefix else digest
    if len(key) > MAX_EXTERNAL_KEY_LENGTH:
        raise ValueError(f"external key longer than {MAX_EXTERNAL_KEY_LENGTH} characters: {key!r}")
    return key


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
