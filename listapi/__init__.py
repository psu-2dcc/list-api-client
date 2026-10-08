"""Python client for the LiST REST API."""

from __future__ import annotations

import os

# Verify TLS against the OS trust store (Windows cert store, macOS keychain)
# instead of certifi's bundle, so servers signed by an organization's internal
# CA work the same as in the browser. Must run before requests/urllib3 build
# any SSL context. Set LISTAPI_NO_TRUSTSTORE=1 to keep certifi.
if not os.environ.get("LISTAPI_NO_TRUSTSTORE"):
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from listapi.auth import sign_in, sign_in_api_key, sign_in_entra, sign_in_shibboleth
from listapi.client import Client
from listapi.errors import ListApiError, SignInCancelled
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
    __version__ = "0.6.1"

__all__ = [
    "Client",
    "ListApiError",
    "SignInCancelled",
    "sign_in",
    "sign_in_api_key",
    "sign_in_entra",
    "sign_in_shibboleth",
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
