"""LiST REST client: samples, activities, files, imports, inventory."""

from __future__ import annotations

import logging
import mimetypes
from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urljoin

import requests

from listapi import ids
from listapi.errors import ListApiError

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 100


class Client:
    """Session-backed LiST API client (Bearer JWT and/or X-API-Key)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        jwt: str | None = None,
        api_version: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.jwt = jwt
        self.api_version = api_version
        self._session = requests.Session()
        if jwt:
            self._session.headers["Authorization"] = f"Bearer {jwt}"
        if api_key:
            self._session.headers["X-API-Key"] = api_key
        self._session.headers.setdefault("Accept", "application/json")

    # -- URL helpers ----------------------------------------------------------

    def _api(self, path: str, *, version: int | None = None) -> str:
        ver = self.api_version if version is None else version
        rel = path.lstrip("/")
        return urljoin(self.base_url + "/", f"api/v{ver}/{rel}")

    def _abs(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return urljoin(self.base_url + "/", path_or_url.lstrip("/"))

    def _request(
        self,
        method: str,
        url: str,
        *,
        timeout: float = 120,
        **kwargs: Any,
    ) -> requests.Response:
        logger.debug("%s %s", method.upper(), url)
        resp = self._session.request(method, url, timeout=timeout, **kwargs)
        return resp

    def _raise(self, resp: requests.Response, what: str) -> None:
        if resp.ok:
            return
        raise ListApiError.from_response(resp, what)

    def request(
        self,
        method: str,
        path: str,
        *,
        version: int | None = None,
        timeout: float = 120,
        **kwargs: Any,
    ) -> Any:
        """
        Call any LiST API path with the current auth (Bearer JWT and/or X-API-Key).

        ``path`` is under ``/api/v{version}/`` (default: this client's ``api_version``),
        e.g. ``"projects"`` or ``"samples/MBE2.123/notes"``. Absolute ``http(s)://…``
        URLs are also accepted. Returns parsed JSON when the body is JSON; otherwise
        the raw :class:`requests.Response`. Raises :class:`ListApiError` on 4xx/5xx.

        See ``{url}/swagger`` for available routes.
        """
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self._api(path, version=version)
        resp = self._request(method, url, timeout=timeout, **kwargs)
        self._raise(resp, f"{method.upper()} {path}")
        if not resp.content:
            return None
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "json" in content_type:
            return resp.json()
        try:
            return resp.json()
        except ValueError:
            return resp

    def get(self, path: str, **kwargs: Any) -> Any:
        """GET helper — see :meth:`request`."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        """POST helper — see :meth:`request`."""
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        """PUT helper — see :meth:`request`."""
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        """PATCH helper — see :meth:`request`."""
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        """DELETE helper — see :meth:`request`."""
        return self.request("DELETE", path, **kwargs)

    # -- Samples --------------------------------------------------------------

    def get_sample(self, sample: int | str | dict[str, Any]) -> dict[str, Any]:
        """GET /api/v{n}/samples/{idOrLabel}."""
        ref = ids.sample_ref(sample)
        url = self._api(f"samples/{ref}")
        resp = self._request("GET", url)
        self._raise(resp, f"GET samples/{ref}")
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected object from get_sample, got {type(data)}")
        return data

    def find_samples(
        self,
        *,
        syn_instrument: str | None = None,
        syn_technique: str | None = None,
        char_instrument: str | None = None,
        char_technique: str | None = None,
        materials: list[int] | None = None,
        material_names: list[str] | None = None,
        elements: list[str] | None = None,
        grown_after: str | date | datetime | None = None,
        grown_before: str | date | datetime | None = None,
        sample_id: str | None = None,
        label: str | None = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        **criteria: Any,
    ) -> list[dict[str, Any]]:
        """
        POST /api/v{n}/samples/search — auto-page until exhausted.

        Synthesis and characterization filters are independent and can be combined
        (same as SampleSearchCriteria on the server):

        - ``syn_instrument`` / ``syn_technique`` → ``instrumentId`` / ``techniqueId``
        - ``char_instrument`` / ``char_technique`` → ``characterizationInstrumentId`` /
          ``characterizationTechniqueId``
        - ``materials`` → catalog material ids; ``material_names`` → names (server resolves
          to ids); ``elements`` → chemical symbols (server resolves to materials)

        Extra kwargs are merged into the search body (camelCase keys preferred).
        Use ``search_kind`` for Active | Snapshot | Both (SampleSearchCriteria.Kind).
        """
        body: dict[str, Any] = {}

        if syn_instrument is not None:
            body["instrumentId"] = syn_instrument
        if syn_technique is not None:
            body["techniqueId"] = syn_technique
        if char_instrument is not None:
            body["characterizationInstrumentId"] = char_instrument
        if char_technique is not None:
            body["characterizationTechniqueId"] = char_technique

        if materials is not None:
            body["materials"] = list(materials)
        if material_names is not None:
            body["materialNames"] = list(material_names)
        if elements is not None:
            body["elements"] = list(elements)

        if grown_after is not None:
            body["grownAfter"] = _as_iso(grown_after)
        if grown_before is not None:
            body["grownBefore"] = _as_iso(grown_before)

        label_val = sample_id or label
        if label_val is not None:
            body["sampleLabel"] = label_val

        for key, value in criteria.items():
            if value is None:
                continue
            if key == "search_kind":
                body["kind"] = value
            else:
                body[key] = _as_iso(value) if isinstance(value, (date, datetime)) else value

        return self._paged_search("samples/search", body, page_size=page_size)

    def create_sample(self, **fields: Any) -> dict[str, Any]:
        """
        POST /api/v{n}/samples/add-to-inventory.

        Accepts ``researcher_key`` as an alias for ``researcherKey``.
        Returns the first created sample DTO (unwraps ``samples[0]`` from the response).
        """
        body = {k: v for k, v in fields.items() if v is not None}
        if "researcher_key" in body and "researcherKey" not in body:
            body["researcherKey"] = body.pop("researcher_key")
        elif "researcher_key" in body:
            body.pop("researcher_key")
        url = self._api("samples/add-to-inventory")
        resp = self._request("POST", url, json=body)
        self._raise(resp, "POST samples/add-to-inventory")
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected object from create_sample, got {type(data)}")
        samples = data.get("samples") or data.get("Samples")
        if isinstance(samples, list) and samples:
            first = samples[0]
            if isinstance(first, dict):
                return first
            raise ValueError("create_sample: samples[0] is not an object")
        # Already a sample-shaped payload (no wrapper).
        if data.get("sampleLabel") is not None or data.get("SampleLabel") is not None:
            return data
        if data.get("id") is not None or data.get("ID") is not None:
            return data
        raise ValueError(f"create_sample: response has no samples[]: {data!r}")

    # -- Data packages --------------------------------------------------------

    def get_data_package(self, id_or_doi: str | int) -> dict[str, Any]:
        """GET /api/v{n}/data-packages/{idOrDoi}."""
        ref = str(id_or_doi)
        url = self._api(f"data-packages/{ref}")
        resp = self._request("GET", url)
        self._raise(resp, f"GET data-packages/{ref}")
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected object from get_data_package, got {type(data)}")
        return data

    def find_data_packages(
        self,
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
        **criteria: Any,
    ) -> list[dict[str, Any]]:
        """POST /api/v{n}/data-packages/search — auto-page."""
        body = {k: v for k, v in criteria.items() if v is not None}
        return self._paged_search("data-packages/search", body, page_size=page_size)

    def _paged_search(
        self,
        path: str,
        body: dict[str, Any],
        *,
        page_size: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        start = 0
        draw = 1
        while True:
            url = self._api(path)
            params = {
                "start": start,
                "length": page_size,
                "draw": draw,
                "sortColumn": "",
                "sortOrder": "",
            }
            resp = self._request("POST", url, params=params, json=body)
            self._raise(resp, f"POST {path}")
            payload = resp.json()
            if isinstance(payload, list):
                results.extend(row for row in payload if isinstance(row, dict))
                break
            if not isinstance(payload, dict):
                raise ValueError(f"Unexpected search response type: {type(payload)}")
            page = payload.get("data") or payload.get("Data") or []
            if not isinstance(page, list):
                raise ValueError("Search response missing data[]")
            results.extend(row for row in page if isinstance(row, dict))
            filtered = payload.get("recordsFiltered")
            if filtered is None:
                filtered = payload.get("RecordsFiltered")
            if len(page) < page_size:
                break
            start += len(page)
            if isinstance(filtered, int) and start >= filtered:
                break
            draw += 1
        return results

    # -- Activities -----------------------------------------------------------

    def activities(
        self,
        sample: int | str | dict[str, Any],
        *,
        kind: str | None = None,
        instrument: str | None = None,
        technique: str | None = None,
        date: str | date | datetime | None = None,
        after: str | date | datetime | None = None,
        before: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        GET sample activities, then filter client-side.

        ``kind``: ``char`` (category CHAR), ``syn`` (type SYN), ``split`` (type DIC).
        ``instrument`` / ``technique`` match DTO fields for both syn and char.
        ``date`` matches the activity calendar day; ``after`` / ``before`` are inclusive bounds.
        """
        ref = ids.sample_ref(sample)
        params: dict[str, str] = {}
        # Server-side charTechnique filter when kind is char (optional optimization).
        if technique and (kind or "").lower() in ("char", "characterization", "c"):
            params["charTechnique"] = str(technique)

        url = self._api(f"samples/{ref}/activities")
        resp = self._request("GET", url, params=params or None)
        self._raise(resp, f"GET samples/{ref}/activities")
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Expected list from activities, got {type(data)}")
        rows = [row for row in data if isinstance(row, dict)]
        return [
            row
            for row in rows
            if _activity_matches(
                row,
                kind=kind,
                instrument=instrument,
                technique=technique,
                on_date=date,
                after=after,
                before=before,
            )
        ]

    def get_sample_activities(self, sample: int | str | dict[str, Any]) -> list[dict[str, Any]]:
        """Alias: all activities for a sample (no client-side filters)."""
        return self.activities(sample)

    def get_sample_activity(self, activity: int | str | dict[str, Any]) -> dict[str, Any]:
        """GET /api/v{n}/sample-activities/{id}."""
        aid = ids.activity_id(activity)
        url = self._api(f"sample-activities/{aid}")
        resp = self._request("GET", url)
        self._raise(resp, f"GET sample-activities/{aid}")
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected object from get_sample_activity, got {type(data)}")
        return data

    def add_activity(
        self,
        sample: int | str | dict[str, Any],
        *,
        kind: str,
        instrument: str | None = None,
        technique: str | None = None,
        date: str | date | datetime | None = None,
        description: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """
        POST /api/v{n}/sample-activities.

        ``kind``: ``syn`` → category PROC, type SYN;
        ``char`` → category CHAR (characterizationTechnique from ``technique``).
        """
        sample_id = ids.sample_numeric_id(
            sample if isinstance(sample, dict) else self.get_sample(sample)
        )
        kind_norm = kind.strip().lower()
        body: dict[str, Any] = {"sampleId": sample_id, **fields}
        if date is not None:
            body["date"] = _as_iso(date)
        if description is not None:
            body["desc"] = description
        if kind_norm in ("syn", "synthesis", "s"):
            body.setdefault("category", "PROC")
            body.setdefault("type", "SYN")
            if instrument is not None:
                body["instrument"] = instrument
            if technique is not None:
                body["technique"] = technique
        elif kind_norm in ("char", "characterization", "c"):
            body.setdefault("category", "CHAR")
            if instrument is not None:
                body["instrument"] = instrument
            if technique is not None:
                body["characterizationTechnique"] = technique
        else:
            raise ValueError(f"add_activity kind must be 'syn' or 'char', got {kind!r}")

        body = {k: v for k, v in body.items() if v is not None}
        url = self._api("sample-activities")
        resp = self._request("POST", url, json=body)
        self._raise(resp, "POST sample-activities")
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected object from add_activity, got {type(data)}")
        return data

    def update_sample_activity(
        self,
        activity: int | str | dict[str, Any],
        body: dict[str, Any],
        *,
        user_has_confirmed: bool = False,
    ) -> dict[str, Any]:
        """PUT /api/v{n}/sample-activities/{id}."""
        aid = ids.activity_id(activity)
        url = self._api(f"sample-activities/{aid}")
        params = {"userHasConfirmed": "true"} if user_has_confirmed else None
        resp = self._request("PUT", url, json=body, params=params)
        self._raise(resp, f"PUT sample-activities/{aid}")
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Expected object from update_sample_activity, got {type(data)}")
        return data

    # -- Files ----------------------------------------------------------------

    def files(self, activity: int | str | dict[str, Any]) -> list[dict[str, Any]]:
        """
        File-group metadata for an activity.

        Prefer ``files`` already on an activity dict; otherwise GET file-groups.
        """
        if isinstance(activity, dict):
            nested = activity.get("files") or activity.get("Files")
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
        return self.get_activity_file_groups(activity)

    def get_activity_file_groups(
        self, activity: int | str | dict[str, Any]
    ) -> list[dict[str, Any]]:
        """GET /api/v{n}/sample-activities/{id}/file-groups."""
        aid = ids.activity_id(activity)
        url = self._api(f"sample-activities/{aid}/file-groups")
        resp = self._request("GET", url)
        self._raise(resp, f"GET sample-activities/{aid}/file-groups")
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Expected list from file-groups, got {type(data)}")
        return [row for row in data if isinstance(row, dict)]

    def file_bytes(
        self, file_or_url_or_activity: str | int | dict[str, Any]
    ) -> bytes:
        """
        Download file content into memory (small spectra / CSV).

        Accepts a download URL string, a file / file-group dict, or an activity
        id/dict (resolves the first file group via :meth:`files` then downloads).
        """
        url = self._resolve_download_url(file_or_url_or_activity)
        resp = self._request("GET", self._abs(url), timeout=300)
        self._raise(resp, f"GET file {url}")
        return resp.content

    def _resolve_download_url(
        self, file_or_url_or_activity: str | int | dict[str, Any]
    ) -> str:
        if isinstance(file_or_url_or_activity, int):
            return self._first_activity_file_url(file_or_url_or_activity)
        if isinstance(file_or_url_or_activity, dict):
            try:
                return ids.file_download_url(file_or_url_or_activity)
            except ValueError:
                return self._first_activity_file_url(file_or_url_or_activity)
        return str(file_or_url_or_activity)

    def _first_activity_file_url(
        self, activity: int | str | dict[str, Any]
    ) -> str:
        groups = self.files(activity)
        if not groups:
            raise ValueError("Activity has no files to download")
        return ids.file_download_url(groups[0])

    def file_stream(self, file_or_url: str | dict[str, Any]) -> requests.Response:
        """Open a streaming GET for a file download URL (caller reads resp.iter_content)."""
        url = (
            ids.file_download_url(file_or_url)
            if isinstance(file_or_url, dict)
            else str(file_or_url)
        )
        resp = self._session.get(self._abs(url), stream=True, timeout=300)
        self._raise(resp, f"GET file stream {url}")
        return resp

    def download(
        self,
        file_or_url: str | dict[str, Any],
        dest: str | Path,
    ) -> Path:
        """Write a file to disk; returns the destination path."""
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_stream(file_or_url) as resp, dest_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fh.write(chunk)
        return dest_path

    def upload_file(
        self,
        activity: int | str | dict[str, Any],
        source: str | Path | bytes | BinaryIO,
        *,
        filename: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v{n}/sample-activities/{id}/files/upload."""
        aid = ids.activity_id(activity)
        name, content = _read_upload_source(source, filename=filename)
        mime = _guess_mime_type(name)
        url = self._api(f"sample-activities/{aid}/files/upload")
        files = {"UploadFile": (name, content, mime)}
        data: dict[str, str] = {}
        if description:
            data["Description"] = description
        resp = self._request("POST", url, files=files, data=data or None, timeout=300)
        self._raise(resp, f"POST sample-activities/{aid}/files/upload")
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object from files/upload, got {type(payload)}")
        return payload

    def upload_activity_file(
        self,
        activity: int | str | dict[str, Any],
        filename: str,
        content: bytes,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Alias matching recipe_pipeline.list_client.upload_activity_file."""
        return self.upload_file(
            activity, content, filename=filename, description=description
        )

    def delete_activity_file(
        self,
        activity: int | str | dict[str, Any],
        file_id: int,
    ) -> None:
        """DELETE /api/v{n}/sample-activities/{id}/files/{fileId}."""
        aid = ids.activity_id(activity)
        url = self._api(f"sample-activities/{aid}/files/{file_id}")
        resp = self._request("DELETE", url)
        self._raise(resp, f"DELETE sample-activities/{aid}/files/{file_id}")

    # -- Sample import (typically v1 / AllowInternalApi) ----------------------

    def list_sample_imports(
        self,
        instrument_id: str,
        *,
        filter_status: str | None = None,
        sample_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/sample-import/{instrumentId}."""
        params: dict[str, str] = {}
        if filter_status:
            params["filterStatus"] = filter_status
        if sample_id:
            params["sampleId"] = sample_id
        url = self._api(f"sample-import/{instrument_id}", version=1)
        resp = self._request("GET", url, params=params)
        self._raise(resp, f"GET sample-import/{instrument_id}")
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Expected list from sample-import API, got {type(data)}")
        return data

    def patch_import_outcome(
        self,
        record_id: int,
        *,
        status: str,
        message: str,
        increment_retries: bool = False,
    ) -> None:
        """PATCH /api/v1/sample-import/{id}/outcome."""
        url = self._api(f"sample-import/{record_id}/outcome", version=1)
        body: dict[str, Any] = {"status": status, "message": message}
        if increment_retries:
            body["incrementRetries"] = True
        resp = self._request("PATCH", url, json=body)
        self._raise(resp, f"PATCH sample-import/{record_id}/outcome")

    def submit_inline_definition(
        self,
        body: str,
        *,
        content_type: str = "application/xml",
        force_update: bool = False,
        recreate_recipe: bool = False,
    ) -> dict[str, Any]:
        """POST /api/v1/sample-import — inline XML/JSON/YAML sample definition."""
        url = self._api("sample-import", version=1)
        params: dict[str, str] = {}
        if force_update:
            params["forceUpdate"] = "true"
        if recreate_recipe:
            params["recreateRecipe"] = "true"
        headers = {
            "Content-Type": content_type,
            "Accept": "application/json",
        }
        resp = self._request(
            "POST",
            url,
            data=body.encode("utf-8"),
            headers=headers,
            params=params or None,
        )
        if resp.status_code in (200, 202):
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"Expected object from sample-import POST, got {type(data)}")
            return data
        self._raise(resp, "POST sample-import")
        raise AssertionError("unreachable")


def _as_iso(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_day(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def _activity_date(row: dict[str, Any]) -> date | None:
    raw = row.get("date") or row.get("Date")
    if raw is None:
        return None
    try:
        return _parse_day(raw)
    except ValueError:
        return None


def _activity_matches(
    row: dict[str, Any],
    *,
    kind: str | None,
    instrument: str | None,
    technique: str | None,
    on_date: str | date | datetime | None,
    after: str | date | datetime | None,
    before: str | date | datetime | None,
) -> bool:
    if kind:
        kn = kind.strip().lower()
        category = str(row.get("category") or row.get("Category") or "").upper()
        typ = str(row.get("type") or row.get("Type") or "").upper()
        if kn in ("char", "characterization", "c"):
            if category != "CHAR":
                return False
        elif kn in ("syn", "synthesis", "s"):
            if typ != "SYN":
                return False
        elif kn in ("split", "dice", "dicing", "dic"):
            if typ != "DIC":
                return False
        else:
            raise ValueError(f"Unknown activity kind {kind!r} (use char, syn, or split)")

    if instrument is not None:
        inst = (
            row.get("instrument")
            or row.get("Instrument")
            or row.get("characterizationInstrumentId")
            or row.get("CharacterizationInstrumentId")
        )
        if str(inst or "") != str(instrument):
            return False

    if technique is not None:
        tech = (
            row.get("technique")
            or row.get("Technique")
            or row.get("characterizationTechnique")
            or row.get("CharacterizationTechnique")
            or row.get("charId")
        )
        if str(tech or "") != str(technique):
            return False

    act_day = _activity_date(row)
    if on_date is not None:
        if act_day is None or act_day != _parse_day(on_date):
            return False
    if after is not None:
        if act_day is None or act_day < _parse_day(after):
            return False
    if before is not None:
        if act_day is None or act_day > _parse_day(before):
            return False
    return True


def _read_upload_source(
    source: str | Path | bytes | BinaryIO,
    *,
    filename: str | None,
) -> tuple[str, bytes]:
    if isinstance(source, bytes):
        if not filename:
            raise ValueError("filename= is required when uploading bytes")
        return filename, source
    if hasattr(source, "read"):
        data = source.read()  # type: ignore[union-attr]
        if isinstance(data, str):
            data = data.encode("utf-8")
        name = filename or getattr(source, "name", None) or "upload.bin"
        return Path(str(name)).name, data
    path = Path(source)
    name = filename or path.name
    return name, path.read_bytes()


def _guess_mime_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".log"):
        return "text/plain"
    if lower.endswith(".csv"):
        return "text/csv"
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
