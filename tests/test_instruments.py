"""Tests for the instrument-history guard against a fake transport (no server needed)."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

import requests
from requests.adapters import BaseAdapter

from listapi import Client, FeatureNotSupported
from listapi.instruments import InstrumentEvent


class FakeServer(BaseAdapter):
    """``has_history`` False mimics a build without instrument history (all its routes answer 404)."""

    def __init__(self) -> None:
        super().__init__()
        self.has_history = True
        self.probe_status: int | None = None  # force the probe's status
        self.calls: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        path = request.path_url
        if path.endswith("/api/v1/system-config"):
            return self._json(request, 200, {
                "environment": "Production",
                "build": {"branch": "release/v2026-10", "commitHash": "d8be031", "buildDate": "11/10/2026"},
            })
        if "/instrument-event-types" in path and request.method == "GET":
            if self.probe_status is not None:
                return self._json(request, self.probe_status, {})
            return self._json(request, 200 if self.has_history else 404, [{"id": "BAKE"}])
        if not self.has_history:
            return self._json(request, 404, {})
        if "/ingest-status" in path:
            return self._json(request, 200, {"eventCount": 0})
        if "/history" in path:
            return self._json(request, 200, {"entries": [], "canEditEvents": True})
        if path.endswith("/events") and request.method == "PUT":
            return self._json(request, 200, {"created": 1, "updated": 0, "unchanged": 0, "results": []})
        return self._json(request, 404, {})

    def probes(self) -> int:
        return sum(1 for c in self.calls if "/instrument-event-types" in c.path_url)

    def close(self) -> None:
        pass

    @staticmethod
    def _json(request, status, payload):  # type: ignore[no-untyped-def]
        resp = requests.Response()
        resp.status_code = status
        resp._content = json.dumps(payload).encode()
        resp.headers["Content-Type"] = "application/json"
        resp.request = request
        resp.url = request.url
        return resp


EVENT = InstrumentEvent(event_type="BAKE", start=datetime(2026, 10, 1, tzinfo=timezone.utc), title="t", external_key="k")


class InstrumentGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()
        self.client = Client("https://list.test", api_key="k")
        self.client._session.mount("https://", self.server)

    def test_supported_build_works_and_probes_once(self) -> None:
        self.client.instrument_history("MBE2")
        self.client.instrument_ingest_status("MBE2")
        self.assertEqual(self.client.push_instrument_events("MBE2", [EVENT]).created, 1)
        self.assertEqual(self.server.probes(), 1)

    def test_old_build_refuses_every_call_before_the_real_request(self) -> None:
        self.server.has_history = False
        calls = [
            lambda: self.client.instrument_history("MBE2"),
            lambda: self.client.instrument_ingest_status("MBE2"),
            lambda: self.client.push_instrument_events("MBE2", [EVENT]),
            lambda: self.client.create_instrument_event("MBE2", EVENT),
            lambda: self.client.update_instrument_event("MBE2", 5, EVENT),
            lambda: self.client.delete_instrument_event("MBE2", "k"),
            lambda: self.client.delete_instrument_event_by_id("MBE2", 5),
            lambda: self.client.list_instrument_event_types(),
        ]
        for call in calls:
            with self.assertRaises(FeatureNotSupported) as cm:
                call()
            self.assertIn("release/v2026-10 @ d8be031", str(cm.exception))
        self.assertEqual(self.server.probes(), 1)
        self.assertFalse([c for c in self.server.calls if "synthesis-instruments" in c.path_url])

    def test_delete_is_not_silently_false_on_old_build(self) -> None:
        self.server.has_history = False
        with self.assertRaises(FeatureNotSupported):
            self.client.delete_instrument_event("MBE2", "k")

    def test_local_validation_runs_before_the_probe(self) -> None:
        with self.assertRaises(ValueError):
            self.client.push_instrument_events("MBE2", [EVENT], batch_size=0)
        self.assertEqual(self.server.probes(), 0)

    def test_check_server_false_skips_the_probe(self) -> None:
        self.server.has_history = False
        self.client.check_server = False
        with self.assertRaises(Exception) as cm:
            self.client.instrument_history("MBE2")
        self.assertNotIsInstance(cm.exception, FeatureNotSupported)
        self.assertEqual(self.server.probes(), 0)

    def test_unclear_probe_attempts_the_call(self) -> None:
        self.server.probe_status = 500
        self.assertIsNone(self.client.instrument_history_supported())
        self.assertEqual(self.client.instrument_history("MBE2")["canEditEvents"], True)


if __name__ == "__main__":
    unittest.main()
