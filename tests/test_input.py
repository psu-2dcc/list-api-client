"""Tests for client.input against a fake transport (no server needed). Run: python -m unittest"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import requests
from requests.adapters import BaseAdapter

from listapi import Client, FeatureNotSupported, ForbiddenError, PayloadTooLargeError, RoleUnknown
from listapi.input import InputMetadata, InputRun, file_sha256


def parse_multipart(request: requests.PreparedRequest) -> tuple[dict, list[tuple[str, bytes]]]:
    """Read the (streamed) request body back into (metadata, [(filename, bytes)])."""
    body = request.body
    raw = body.read() if hasattr(body, "read") else body
    assert len(raw) == int(request.headers["Content-Length"]), "Content-Length must match the body"
    boundary = request.headers["Content-Type"].split("boundary=")[1].encode()
    meta: dict = {}
    files: list[tuple[str, bytes]] = []
    for part in raw.split(b"--" + boundary)[1:-1]:
        head, _, content = part.partition(b"\r\n\r\n")
        content = content[:-2]
        if b'name="metadata"' in head:
            meta = json.loads(content)
        else:
            name = head.split(b'filename="')[1].split(b'"')[0].decode()
            files.append((name, content))
    return meta, files


class FakeServer(BaseAdapter):
    """Mimics POST input: 202 first time, 200 when same key+content, 403/413 by rule."""

    def __init__(self) -> None:
        super().__init__()
        self.known: dict[str, str] = {}
        self.calls: list[requests.PreparedRequest] = []
        self.fail_next: list[int] = []
        self.own_instruments = {"MBE2"}
        self.max_bytes = 1 << 30
        self.has_input = True  # False: an older build without the input controller
        self.schema_status = 200

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        path = request.path_url
        if path.endswith("/api/v1/system-config"):
            return self._json(request, 200, {
                "environment": "Production",
                "build": {"branch": "release/v2026-10", "commitHash": "d8be031", "buildDate": "11/10/2026", "version": "1.0.0"},
            })
        if path.endswith("/input/schema"):
            return self._json(request, self.schema_status if self.has_input else 404, {})
        if not self.has_input and "/input" in path:
            return self._json(request, 404, {})
        if self.fail_next:
            return self._json(request, self.fail_next.pop(0), {"title": "boom"})
        if request.method == "POST" and path.endswith("/api/v2/input"):
            meta, files = parse_multipart(request)
            request.parsed = (meta, files)  # type: ignore[attr-defined]
            if meta.get("instrument") not in self.own_instruments:
                return self._json(request, 403, {"detail": "Instrument is not this Gatekeeper's"})
            if any(len(c) > self.max_bytes for _, c in files):
                return self._json(request, 413, {"detail": "File too large"})
            items, created = [], False
            for i, ((name, content), entry) in enumerate(zip(files, meta["files"]), start=1):
                if entry["sha256"] != hashlib.sha256(content).hexdigest():
                    return self._json(request, 400, {"detail": "sha256 mismatch"})
                key = entry["externalKey"]
                digest = entry["sha256"]
                existing = self.known.get(key) == digest
                if not existing:
                    created = True
                    self.known[key] = digest
                items.append({"id": i, "fileName": name, "status": "R", "existing": existing})
            return self._json(request, 202 if created else 200, {"submissionId": "s1", "items": items})
        if request.method == "POST" and path.endswith("/api/v2/input/exists"):
            rows = json.loads(request.body)["items"]
            return self._json(
                request,
                200,
                {"items": [
                    {"externalKey": r["externalKey"], "known": self.known.get(r["externalKey"]) == r["sha256"]}
                    for r in rows
                ]},
            )
        return self._json(request, 404, {})

    def real_calls(self) -> list:
        """Calls other than the one-time support probe."""
        return [c for c in self.calls if not c.path_url.endswith("/input/schema")]

    def pushes(self) -> list:
        return [c for c in self.calls if c.method == "POST" and c.path_url.endswith("/api/v2/input")]

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


class InputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()
        self.client = Client("https://list.test", api_key="gk-key")
        self.client._session.mount("https://", self.server)
        self.client.input.backoff = 0
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, name: str, data: bytes = b"hello") -> Path:
        path = self.tmp / name
        path.write_bytes(data)
        return path

    # -- unit ---------------------------------------------------------------------------------

    def test_metadata_omits_absent_values(self) -> None:
        body = InputMetadata(instrument="MBE2", sample="", user=None, run=InputRun(key="r1", index=None),
                             fields={"a": ""}).to_json()
        self.assertEqual(body, {"schema": "list-input/1", "instrument": "MBE2", "run": {"key": "r1"}})

    def test_dict_metadata_drops_empty_strings(self) -> None:
        self.write("a.rcp")
        self.client.input.push([(self.tmp / "a.rcp", "recipe")], {"instrument": "MBE2", "sample": "", "user": None})
        meta = self.server.pushes()[0].parsed[0]
        self.assertNotIn("sample", meta)
        self.assertNotIn("user", meta)

    def test_unknown_role_raised_locally(self) -> None:
        path = self.write("a.rcp")
        with self.assertRaises(RoleUnknown):
            self.client.input.push([(path, "recipee")], {"instrument": "MBE2"})
        self.assertEqual(self.server.calls, [])  # not even the probe
        with self.assertRaises(RoleUnknown):
            InputMetadata(files=[{"name": "a", "role": "SYN"}]).to_json()

    def test_sha256_matches_and_streams_in_chunks(self) -> None:
        data = b"x" * (3 * 1024 * 1024 + 17)
        path = self.write("big.log", data)
        self.assertEqual(file_sha256(path), hashlib.sha256(data).hexdigest())
        self.client.input.push([(path, "log")], {"instrument": "MBE2"})
        meta, files = self.server.pushes()[0].parsed
        self.assertEqual(meta["files"][0]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(files[0][1], data)

    def test_default_key_role_and_order(self) -> None:
        a, b = self.write("run1.rcp"), self.write("run1.log")
        self.client.input.push([(a, "recipe"), (b, "log")], {"instrument": "MBE2"})
        meta, files = self.server.pushes()[0].parsed
        self.assertEqual([f["externalKey"] for f in meta["files"]], ["MBE2/recipe/run1.rcp", "MBE2/log/run1.log"])
        self.assertEqual([n for n, _ in files], ["run1.rcp", "run1.log"])
        self.assertEqual(meta["schema"], "list-input/1")

    def test_run_key_goes_into_default_key(self) -> None:
        self.client.input.push([(self.write("g.rcp"), "recipe")], {"instrument": "MBE2", "run": {"key": "r1"}})
        meta = self.server.pushes()[0].parsed[0]
        self.assertEqual(meta["files"][0]["externalKey"], "MBE2/r1/recipe/g.rcp")

    def test_gatekeeper_key_sent_every_call_v2_no_exchange(self) -> None:
        self.write("a.rcp")
        self.client.input.push([(self.tmp / "a.rcp", "recipe")], {"instrument": "MBE2"})
        req = self.server.pushes()[0]
        self.assertEqual(req.headers["X-API-Key"], "gk-key")
        self.assertNotIn("Authorization", req.headers)
        self.assertIn("/api/v2/input", req.url)

    # -- against the fake server --------------------------------------------------------------

    def test_202_then_200_idempotent(self) -> None:
        path = self.write("a.rcp")
        first = self.client.input.push([(path, "recipe")], {"instrument": "MBE2"})
        self.assertTrue(first.created)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.items[0].file_name, "a.rcp")
        again = self.client.input.push([(path, "recipe")], {"instrument": "MBE2"})
        self.assertFalse(again.created)
        self.assertTrue(again.items[0].existing)

    def test_exists_marks_pushed_key_known(self) -> None:
        path = self.write("a.rcp")
        self.client.input.push([(path, "recipe")], {"instrument": "MBE2"})
        digest = file_sha256(path)
        got = self.client.input.exists([("MBE2/recipe/a.rcp", digest), ("MBE2/recipe/b.rcp", digest)])
        self.assertEqual([(r.external_key, r.known) for r in got],
                         [("MBE2/recipe/a.rcp", True), ("MBE2/recipe/b.rcp", False)])

    def test_exists_splits_at_500(self) -> None:
        rows = [(f"k{i}", "00") for i in range(1001)]
        self.assertEqual(len(self.client.input.exists(rows)), 1001)
        self.assertEqual(len(self.server.real_calls()), 3)

    def test_403_foreign_instrument(self) -> None:
        path = self.write("a.rcp")
        with self.assertRaises(ForbiddenError) as ctx:
            self.client.input.push([(path, "recipe")], {"instrument": "OTHER"})
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("not this Gatekeeper", ctx.exception.detail)

    def test_413_too_large(self) -> None:
        self.server.max_bytes = 3
        path = self.write("a.rcp", b"too long")
        with self.assertRaises(PayloadTooLargeError) as ctx:
            self.client.input.push([(path, "recipe")], {"instrument": "MBE2"})
        self.assertEqual(ctx.exception.status_code, 413)

    def test_retries_5xx_then_succeeds(self) -> None:
        self.server.fail_next = [503, 502]
        result = self.client.input.push([(self.write("a.rcp"), "recipe")], {"instrument": "MBE2"})
        self.assertTrue(result.created)
        self.assertEqual(len(self.server.real_calls()), 3)

    def test_4xx_not_retried(self) -> None:
        self.server.fail_next = [400]
        with self.assertRaises(Exception):
            self.client.input.push([(self.write("a.rcp"), "recipe")], {"instrument": "MBE2"})
        self.assertEqual(len(self.server.real_calls()), 1)

    def test_push_folder_groups_roles_and_skips_known(self) -> None:
        for name in ("run1.log", "run1.rcp", "run1.csv", "notes.txt"):
            self.write(name)
        first = self.client.input.push_folder(self.tmp, "MBE2")
        meta, files = self.server.pushes()[-1].parsed
        self.assertEqual([n for n, _ in files], ["run1.rcp", "run1.log", "run1.csv"])
        self.assertEqual([f["role"] for f in meta["files"]], ["recipe", "log", "data"])
        self.assertTrue(first.created)
        n = len(self.server.real_calls())
        second = self.client.input.push_folder(self.tmp, "MBE2")
        self.assertFalse(second.created)
        self.assertEqual(second.items, [])
        self.assertEqual(len(self.server.real_calls()), n + 1)  # only the exists call

    # -- server support -------------------------------------------------------------------------

    def test_old_build_refused_before_any_upload(self) -> None:
        self.server.has_input = False
        path = self.write("a.rcp", b"x" * 1000)
        with self.assertRaises(FeatureNotSupported) as ctx:
            self.client.input.push([(path, "recipe")], {"instrument": "MBE2"})
        self.assertIn("release/v2026-10", str(ctx.exception))
        self.assertEqual(ctx.exception.server["commitHash"], "d8be031")
        self.assertFalse([c for c in self.server.calls if c.method == "POST"])
        with self.assertRaises(FeatureNotSupported):
            self.client.input.status()
        self.assertEqual(self.client.input.supported(), False)

    def test_probe_is_cached(self) -> None:
        self.write("a.rcp")
        for _ in range(3):
            self.client.input.push([(self.tmp / "a.rcp", "recipe")], {"instrument": "MBE2"})
        self.assertEqual(len([c for c in self.server.calls if c.path_url.endswith("/input/schema")]), 1)

    def test_unknown_probe_result_still_tries(self) -> None:
        self.server.schema_status = 500
        result = self.client.input.push([(self.write("a.rcp"), "recipe")], {"instrument": "MBE2"})
        self.assertTrue(result.created)
        self.assertIsNone(self.client.input.supported())

    def test_check_can_be_switched_off(self) -> None:
        self.server.has_input = False
        self.client.input.check_server = False
        from listapi import NotFoundError
        with self.assertRaises(NotFoundError):
            self.client.input.push([(self.write("a.rcp"), "recipe")], {"instrument": "MBE2"})

    def test_server_info_reads_build(self) -> None:
        info = self.client.server_info()
        self.assertEqual((info["branch"], info["environment"]), ("release/v2026-10", "Production"))


if __name__ == "__main__":
    unittest.main()
