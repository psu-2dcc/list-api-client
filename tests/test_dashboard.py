"""Tests for Client.upload_dashboard against a fake transport (no server needed). Run: python -m unittest"""

from __future__ import annotations

import json
import unittest

import requests
from requests.adapters import BaseAdapter

from listapi import Client, FeatureNotSupported, NotFoundError

HTML = b"<html><body>hi</body></html>"


class FakeServer(BaseAdapter):
    """Activity 7 exists. ``has_route`` False mimics a build without files/upload-dashboard."""

    def __init__(self) -> None:
        super().__init__()
        self.has_route = True
        self.calls: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        path = request.path_url
        if path.endswith("/api/v1/system-config"):
            return self._json(request, 200, {
                "environment": "Production",
                "build": {"branch": "release/v2026-10", "commitHash": "d8be031", "buildDate": "11/10/2026"},
            })
        if request.method == "GET" and path.endswith("/sample-activities/7"):
            return self._json(request, 200, {"id": 7})
        if request.method == "POST" and path.endswith("/sample-activities/7/files/upload-dashboard") and self.has_route:
            return self._json(request, 200, {"id": 1, "fileName": "d.html", "isDashboard": True})
        return self._json(request, 404, {})

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


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()
        self.client = Client("https://list.test", api_key="k")
        self.client._session.mount("https://", self.server)

    def test_upload(self) -> None:
        out = self.client.upload_dashboard(7, HTML, filename="d.html")
        self.assertTrue(out["isDashboard"])

    def test_requires_html_name(self) -> None:
        with self.assertRaises(ValueError):
            self.client.upload_dashboard(7, b"x", filename="d.txt")
        self.assertEqual(self.server.calls, [])

    def test_old_server_names_the_build(self) -> None:
        self.server.has_route = False
        with self.assertRaises(FeatureNotSupported) as cm:
            self.client.upload_dashboard(7, HTML, filename="d.html")
        self.assertIn("release/v2026-10 @ d8be031", str(cm.exception))
        self.assertEqual(cm.exception.server["commitHash"], "d8be031")

    def test_missing_activity_is_a_plain_404(self) -> None:
        with self.assertRaises(NotFoundError):
            self.client.upload_dashboard(8, HTML, filename="d.html")


if __name__ == "__main__":
    unittest.main()
