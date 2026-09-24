"""Python client for the LiST REST API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from listapi.auth import sign_in
from listapi.client import Client
from listapi.errors import ListApiError
from listapi.import_status import (
    DEFAULT_IMPORT_STATUSES,
    FILTER_ALL,
    FILTER_ANY_ISSUE,
    FILTER_ERROR,
    FILTER_INCOMPLETE,
    FILTER_OK,
    FORCE_IMPORT_STATUSES,
    IMPORT_STATUS_DESCRIPTIONS,
    STATUS_CONFLICT,
    STATUS_CREATED,
    STATUS_ERROR,
    STATUS_INCOMPLETE,
    STATUS_NOTHING_TO_DO,
    STATUS_PENDING,
    STATUS_UPDATED,
    describe_import_status,
)

try:
    __version__ = _pkg_version("listapi")
except PackageNotFoundError:
    # Source tree without an install (e.g. raw path on sys.path).
    __version__ = "0.2.0"

__all__ = [
    "Client",
    "ListApiError",
    "sign_in",
    "__version__",
    "STATUS_INCOMPLETE",
    "STATUS_ERROR",
    "STATUS_NOTHING_TO_DO",
    "STATUS_CREATED",
    "STATUS_UPDATED",
    "STATUS_PENDING",
    "STATUS_CONFLICT",
    "IMPORT_STATUS_DESCRIPTIONS",
    "DEFAULT_IMPORT_STATUSES",
    "FORCE_IMPORT_STATUSES",
    "FILTER_ALL",
    "FILTER_INCOMPLETE",
    "FILTER_OK",
    "FILTER_ANY_ISSUE",
    "FILTER_ERROR",
    "describe_import_status",
]
