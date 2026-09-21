"""Python client for the LiST REST API."""

from __future__ import annotations

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

__all__ = [
    "Client",
    "ListApiError",
    "sign_in",
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

__version__ = "0.1.0"
