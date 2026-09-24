"""
LiST MCP server (stdio).

Authenticate once at process start via ``sign_in()`` (API key from env/config,
or Entra when no key), then expose read-oriented Client methods as tools.

Install: ``pip install 'listapi[mcp]'`` (or ``pip install '.[mcp]'`` from this repo).
Run: ``listapi-mcp`` or ``python -m listapi.mcp_server``.

Logs go to stderr only — stdout is reserved for MCP JSON-RPC.
"""

from __future__ import annotations

import json
import logging
import sys

logger = logging.getLogger("listapi.mcp")

# Cap tool payloads so hosts are not flooded with huge file dumps.
_DEFAULT_FIND_LIMIT = 50
_FILE_BYTES_MAX = 256 * 1024


def _json(data: Any) -> str:
    return json.dumps(data, default=str)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        print(
            "MCP extra not installed. Run: pip install 'listapi[mcp]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    from listapi import ListApiError, sign_in

    logger.info("Signing in to LiST…")
    try:
        client = sign_in()
    except Exception as exc:
        logger.error("Sign-in failed: %s", exc)
        raise SystemExit(1) from exc
    logger.info("Signed in to %s", client.base_url)

    mcp = FastMCP(
        "listapi",
        instructions=(
            "LiST laboratory sample inventory API. "
            "Use find_samples / sample_stats / get_sample for discovery; "
            "activities and files for characterization data."
        ),
    )

    @mcp.tool()
    def find_samples(
        syn_instrument: str | None = None,
        syn_technique: str | None = None,
        char_instrument: str | None = None,
        char_technique: str | None = None,
        materials: list[int] | None = None,
        material_names: list[str] | None = None,
        elements: list[str] | None = None,
        grown_after: str | None = None,
        grown_before: str | None = None,
        sample_id: str | None = None,
        limit: int = _DEFAULT_FIND_LIMIT,
    ) -> str:
        """Search samples (SampleSearchCriteria). Returns JSON list, truncated to limit."""
        try:
            rows = client.find_samples(
                syn_instrument=syn_instrument,
                syn_technique=syn_technique,
                char_instrument=char_instrument,
                char_technique=char_technique,
                materials=materials,
                material_names=material_names,
                elements=elements,
                grown_after=grown_after,
                grown_before=grown_before,
                sample_id=sample_id,
            )
        except ListApiError as exc:
            return _json({"error": str(exc)})
        truncated = rows[: max(1, limit)]
        return _json(
            {
                "total": len(rows),
                "returned": len(truncated),
                "samples": truncated,
            }
        )

    @mcp.tool()
    def sample_stats(
        syn_instrument: str | None = None,
        syn_technique: str | None = None,
        char_instrument: str | None = None,
        char_technique: str | None = None,
        materials: list[int] | None = None,
        material_names: list[str] | None = None,
        elements: list[str] | None = None,
        grown_after: str | None = None,
        grown_before: str | None = None,
        sample_id: str | None = None,
    ) -> str:
        """Aggregated sample statistics for the same filters as find_samples."""
        try:
            rows = client.sample_stats(
                syn_instrument=syn_instrument,
                syn_technique=syn_technique,
                char_instrument=char_instrument,
                char_technique=char_technique,
                materials=materials,
                material_names=material_names,
                elements=elements,
                grown_after=grown_after,
                grown_before=grown_before,
                sample_id=sample_id,
            )
        except ListApiError as exc:
            return _json({"error": str(exc)})
        return _json(rows)

    @mcp.tool()
    def get_sample(sample: str) -> str:
        """Fetch one sample by label or numeric id."""
        try:
            return _json(client.get_sample(sample))
        except ListApiError as exc:
            return _json({"error": str(exc)})

    @mcp.tool()
    def activities(
        sample: str,
        kind: str | None = None,
        instrument: str | None = None,
        technique: str | None = None,
        date: str | None = None,
    ) -> str:
        """List activities for a sample. kind: syn | char | split."""
        try:
            rows = client.activities(
                sample,
                kind=kind,
                instrument=instrument,
                technique=technique,
                date=date,
            )
        except ListApiError as exc:
            return _json({"error": str(exc)})
        return _json(rows)

    @mcp.tool()
    def files(activity: str) -> str:
        """List file groups / metadata for an activity (id or activity dict id)."""
        try:
            return _json(client.files(activity))
        except ListApiError as exc:
            return _json({"error": str(exc)})

    @mcp.tool()
    def file_bytes(file_or_activity: str, max_bytes: int = _FILE_BYTES_MAX) -> str:
        """
        Download file content for an activity or file URL/object.
        Returns base64 and length; truncates when larger than max_bytes.
        """
        import base64

        try:
            raw = client.file_bytes(file_or_activity)
        except ListApiError as exc:
            return _json({"error": str(exc)})
        truncated = len(raw) > max_bytes
        payload = raw[:max_bytes]
        return _json(
            {
                "size": len(raw),
                "returned": len(payload),
                "truncated": truncated,
                "base64": base64.b64encode(payload).decode("ascii"),
            }
        )

    @mcp.tool()
    def find_data_packages(criteria_json: str = "{}", limit: int = _DEFAULT_FIND_LIMIT) -> str:
        """
        Search data packages. Pass a JSON object of DataPackageSearchCriteria
        fields (camelCase), e.g. '{"projectId":"42"}'.
        """
        try:
            criteria = json.loads(criteria_json) if criteria_json else {}
            if not isinstance(criteria, dict):
                return _json({"error": "criteria_json must be a JSON object"})
            rows = client.find_data_packages(**criteria)
        except (ListApiError, json.JSONDecodeError, TypeError) as exc:
            return _json({"error": str(exc)})
        truncated = rows[: max(1, limit)]
        return _json(
            {
                "total": len(rows),
                "returned": len(truncated),
                "packages": truncated,
            }
        )

    @mcp.tool()
    def api_get(path: str) -> str:
        """GET any /api/v{n}/ path relative to the client (e.g. 'projects')."""
        try:
            return _json(client.get(path))
        except ListApiError as exc:
            return _json({"error": str(exc)})

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
