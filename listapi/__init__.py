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
from listapi.errors import (
    BadRequestError,
    FeatureNotSupported,
    ForbiddenError,
    ListApiError,
    NotFoundError,
    PayloadTooLargeError,
    RoleUnknown,
    SignInCancelled,
)
from listapi.input import (
    ROLE_CHARACTERIZATION,
    ROLE_DATA,
    ROLE_LOG,
    ROLE_RECIPE,
    ROLE_SAMPLE_DEFINITION,
    ROLES,
    SCHEMA_V1,
    STATUS_DISCARDED,
    STATUS_DONE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_MOVING,
    STATUS_QUEUED,
    STATUS_RECEIVED,
    STATUS_WAITING,
    STATUS_LABELS,
    ExistsResult,
    InputFileEntry,
    InputMetadata,
    InputNamespace,
    InputPushResult,
    InputRun,
    InputSource,
    ItemState,
    PushedItem,
    PushFile,
    PushResult,
    describe_input_error,
    describe_input_status,
    file_sha256,
)
from listapi.instruments import InstrumentEvent, InstrumentPushError, InstrumentPushResult, stable_key
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
    __version__ = "0.9.0"

__all__ = [
    "Client",
    "ListApiError",
    "SignInCancelled",
    "InstrumentEvent",
    "InstrumentPushError",
    "InstrumentPushResult",
    "stable_key",
    "BadRequestError",
    "FeatureNotSupported",
    "ForbiddenError",
    "NotFoundError",
    "PayloadTooLargeError",
    "RoleUnknown",
    "InputMetadata",
    "InputFileEntry",
    "InputRun",
    "InputSource",
    "InputNamespace",
    "PushFile",
    "PushResult",
    "PushedItem",
    "InputPushResult",
    "ExistsResult",
    "ItemState",
    "SCHEMA_V1",
    "ROLES",
    "ROLE_SAMPLE_DEFINITION",
    "ROLE_RECIPE",
    "ROLE_LOG",
    "ROLE_DATA",
    "ROLE_CHARACTERIZATION",
    "STATUS_RECEIVED",
    "STATUS_QUEUED",
    "STATUS_MOVING",
    "STATUS_WAITING",
    "STATUS_FAILED",
    "STATUS_DONE",
    "STATUS_DISCARDED",
    "STATUS_DUPLICATE",
    "STATUS_LABELS",
    "describe_input_status",
    "describe_input_error",
    "file_sha256",
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
