# Instrument history from instrument-side scripts

LiST shows a history per synthesis instrument: sample runs and events such as maintenance, cleaning runs, bakeouts
and calibrations. Assembling events from an instrument's own logs is instrument-specific, so a script **at the
instrument** reads them and pushes them to LiST with `listapi`.

> Pair with a LiST build that has instrument history ingest (`PUT/POST synthesis-instruments/{id}/events`).
> A Gatekeeper key with InstrumentHistory Create+Update is the usual setup when the same machine also pushes files
> into the input queue ([input-queue.md](input-queue.md)).

## Setup in LiST (admin)

1. A role for pushing (e.g. the Gatekeeper role) with **InstrumentHistory** Create and Update (Delete if the script
   should remove events).
2. An **API key** on a **Gatekeeper** that lists the instrument(s), or a role-based key that lists them under
   Instrument history. The key can only change those instruments' history.
3. Event types (Customizing → Instrument event types): the IDs the script sends, e.g. `MAINT`, `CLEAN`, `BAKE`,
   `CALIB`, `OTHER` (`client.list_instrument_event_types()`).

## The script

```python
from datetime import datetime, timezone
from listapi import sign_in_api_key
from listapi.instruments import InstrumentEvent, InstrumentPushError, stable_key

client = sign_in_api_key("https://list.example.org", api_key)
start = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
events = [
    InstrumentEvent(
        external_key=stable_key("bakeout", start.isoformat(), prefix="mbe2-log"),
        event_type="BAKE",
        start=start,
        duration_hours=36,
        title="Bakeout after cell refill",
        description="<p>Cells 3 and 5 refilled.</p>",
    ),
]
try:
    result = client.push_instrument_events("MBE2", events)
    print(result.created, result.updated, result.unchanged)
except InstrumentPushError as e:
    print(e)  # every invalid item with its index; nothing of that batch was saved
```

- **External key**: the instrument system's id for the event, or `stable_key(...)` over what identifies a log entry
  (type and start time). The same key always means the same event, so pushing the whole log again only updates
  what changed: no state on the PC.
- **Times**: timezone-aware datetimes, or naive ones (taken as UTC).
- **Description**: HTML; LiST sanitizes it like notes.
- **Batches**: up to 1000 events per request; longer lists are split. Each batch is all or nothing.
- **Delete**: `client.delete_instrument_event("MBE2", external_key)` or `delete_instrument_event_by_id`.
- **Status**: `client.instrument_ingest_status("MBE2")` — number of pushed events, latest start, latest change.
- **Read / UI-style write**: `client.instrument_history("MBE2")`, `create_instrument_event`, `update_instrument_event`
  (no external key; use push from scripts so re-runs stay idempotent).
- Events edited in LiST's UI are overwritten by the next push of the same event.

`examples/instrument_log_push.py` is a template (CSV log, type mapping, `--dry-run`) to copy to an instrument PC
and adapt to its log format; run it on a schedule.
