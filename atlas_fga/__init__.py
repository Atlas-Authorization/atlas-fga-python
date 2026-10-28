"""atlas-fga — the Atlas FGA client for Python.

Fine-grained, relationship-based authorization (Zanzibar / OpenFGA) served by
Atlas's in-house engine at the Backend API's ``/v1/fga`` surface.

This is a NATIVE client, not a wrapper over the ``openfga-sdk`` package: Atlas's
FGA API is OpenFGA-SHAPED but not byte-for-byte wire-identical (it wraps
responses in an ``{"object": ...}`` envelope, returns ``read`` as a list page,
and mounts ``list-objects`` / ``read`` / ``expand`` only on ``/v1/fga`` — the
OpenFGA wire-compatible mirror at ``/v1/openfga`` covers only
check / write / stores / models). See the README "Relationship to OpenFGA".

Zero runtime dependencies — HTTP over the standard library's ``urllib``.
Authenticated with an Atlas secret key: ``Authorization: Bearer sk_...``.

    from atlas_fga import AtlasFga
    fga = AtlasFga(secret_key="sk_live_...", store_id="store_123")
    fga.write_tuples([{"user": "user:alice", "relation": "viewer", "object": "doc:readme"}])
    fga.check(user="user:alice", relation="viewer", object="doc:readme").allowed  # True
"""

from .client import (
    DEFAULT_BASE_URL,
    AtlasFga,
    AtlasFgaError,
    AuthorizationModel,
    BatchCheckResult,
    BoundStore,
    ChangesPage,
    CheckResult,
    ExpandResult,
    ListObjectsResult,
    ListPage,
    ListUsersResult,
    Store,
    Tuple,
    TupleChange,
    WriteResult,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "AtlasFga",
    "AtlasFgaError",
    "AuthorizationModel",
    "BatchCheckResult",
    "BoundStore",
    "ChangesPage",
    "CheckResult",
    "ExpandResult",
    "ListObjectsResult",
    "ListPage",
    "ListUsersResult",
    "Store",
    "Tuple",
    "TupleChange",
    "WriteResult",
]

__version__ = "0.1.0"
