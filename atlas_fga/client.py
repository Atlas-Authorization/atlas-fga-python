"""The Atlas FGA client and its wire types."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

DEFAULT_BASE_URL = "https://api.atlasauth.net"

#: A pluggable transport: ``(method, url, headers, body) -> (status, bytes)``.
#: The default is urllib-based; tests inject their own.
Transport = Callable[[str, str, Dict[str, str], Optional[bytes]], "tuple[int, bytes]"]

# A tuple key is just a mapping with user / relation / object.
TupleKey = Dict[str, str]


# ---- wire types --------------------------------------------------------------


@dataclass
class CheckResult:
    allowed: bool
    authorization_model_id: str = ""
    object: str = "fga.check"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CheckResult":
        return cls(
            allowed=bool(d.get("allowed", False)),
            authorization_model_id=d.get("authorization_model_id", ""),
            object=d.get("object", "fga.check"),
        )


@dataclass
class WriteResult:
    writes: int
    deletes: int
    object: str = "fga.write_result"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WriteResult":
        return cls(
            writes=int(d.get("writes", 0)),
            deletes=int(d.get("deletes", 0)),
            object=d.get("object", "fga.write_result"),
        )


@dataclass
class ListObjectsResult:
    objects: List[str]
    authorization_model_id: str = ""
    object: str = "fga.list_objects"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ListObjectsResult":
        return cls(
            objects=list(d.get("objects", [])),
            authorization_model_id=d.get("authorization_model_id", ""),
            object=d.get("object", "fga.list_objects"),
        )


@dataclass
class ExpandResult:
    tree: Any
    authorization_model_id: str = ""
    object: str = "fga.expand"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExpandResult":
        return cls(
            tree=d.get("tree"),
            authorization_model_id=d.get("authorization_model_id", ""),
            object=d.get("object", "fga.expand"),
        )


@dataclass
class BatchCheckResult:
    result: List[Dict[str, Any]]
    authorization_model_id: str = ""
    object: str = "fga.batch_check"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BatchCheckResult":
        return cls(
            result=list(d.get("result", [])),
            authorization_model_id=d.get("authorization_model_id", ""),
            object=d.get("object", "fga.batch_check"),
        )


@dataclass
class Tuple:
    user: str
    relation: str
    target: str
    created_at: int = 0
    object: str = "fga.tuple"


@dataclass
class Store:
    id: str
    name: str
    created_at: int = 0
    updated_at: int = 0
    object: str = "fga.store"


@dataclass
class AuthorizationModel:
    id: str
    store_id: str
    schema_version: str
    model: Optional[Dict[str, Any]] = None
    created_at: int = 0
    object: str = "fga.authorization_model"


@dataclass
class ListPage:
    """The Atlas ``{object:'list', data, has_more}`` page envelope."""

    data: List[Dict[str, Any]]
    has_more: bool = False
    object: str = "list"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ListPage":
        return cls(
            data=list(d.get("data", [])),
            has_more=bool(d.get("has_more", False)),
            object=d.get("object", "list"),
        )


# ---- errors ------------------------------------------------------------------


@dataclass
class AtlasFgaError(Exception):
    """Raised for any non-2xx response; carries the Atlas §9.1 error envelope."""

    status: int
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        msg = self.errors[0].get("message") if self.errors else None
        super().__init__(msg or f"Atlas FGA request failed (HTTP {self.status}).")

    @property
    def code(self) -> Optional[str]:
        """The first error code (e.g. ``store_id_not_found``)."""
        return self.errors[0].get("code") if self.errors else None


# ---- transport ---------------------------------------------------------------


def _urllib_transport(
    method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
) -> "tuple[int, bytes]":
    req = urllib.request.Request(url=url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 - fixed Atlas origin
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:  # non-2xx still carries a body
        return exc.code, exc.read()


# ---- client ------------------------------------------------------------------


class AtlasFga:
    """The Atlas FGA client. Construct once and reuse.

    When a default ``store_id`` is configured, the store-scoped operations are
    callable straight off the client; otherwise bind one with ``.store(id)``.
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        *,
        store_id: Optional[str] = None,
        authorization_model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        transport: Optional[Transport] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        key = secret_key or os.environ.get("ATLAS_SECRET_KEY")
        if not key:
            raise ValueError(
                "AtlasFga: a secret key is required (pass secret_key= or set ATLAS_SECRET_KEY)."
            )
        self._secret_key = key
        self.base_url = (
            base_url or os.environ.get("ATLAS_FGA_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._store_id = store_id or os.environ.get("ATLAS_FGA_STORE_ID")
        self._model_id = authorization_model_id or os.environ.get("ATLAS_FGA_MODEL_ID")
        self._transport = transport or _urllib_transport
        self._extra_headers = headers or {}

    # -- internal --

    def _request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._secret_key}",
            "Accept": "application/json",
            "User-Agent": "atlasauth-fga-python",
            **self._extra_headers,
        }
        data: Optional[bytes] = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        status, raw = self._transport(method, f"{self.base_url}{path}", headers, data)
        parsed = json.loads(raw) if raw else None
        if not (200 <= status < 300):
            errors = (
                parsed["errors"]
                if isinstance(parsed, dict) and isinstance(parsed.get("errors"), list)
                else [{"code": "request_failed", "message": raw.decode("utf-8", "replace")}]
            )
            raise AtlasFgaError(status=status, errors=errors)
        return parsed

    def _store(self, explicit: Optional[str]) -> str:
        store = explicit or self._store_id
        if not store:
            raise ValueError(
                "AtlasFga: no store id (set store_id= / ATLAS_FGA_STORE_ID, or use .store(id))."
            )
        return store

    def _with_model(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if body.get("authorization_model_id") is None and self._model_id is not None:
            body = {**body, "authorization_model_id": self._model_id}
        return body

    # -- store-scoped operations --

    def check(
        self,
        *,
        user: str,
        relation: str,
        object: str,  # noqa: A002 - matches the OpenFGA tuple vocabulary
        authorization_model_id: Optional[str] = None,
        contextual_tuples: Optional[List[TupleKey]] = None,
        store_id: Optional[str] = None,
    ) -> CheckResult:
        """Resolve a single access question."""
        store = self._store(store_id)
        body = self._with_model(
            {
                "user": user,
                "relation": relation,
                "object": object,
                "authorization_model_id": authorization_model_id,
                "contextual_tuples": contextual_tuples,
            }
        )
        body = {k: v for k, v in body.items() if v is not None}
        return CheckResult.from_dict(self._request("POST", f"/v1/fga/stores/{quote(store)}/check", body))

    def write(
        self,
        *,
        writes: Optional[List[TupleKey]] = None,
        deletes: Optional[List[TupleKey]] = None,
        idempotency_key: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> WriteResult:
        """Write and/or delete tuples in one atomic call."""
        store = self._store(store_id)
        body: Dict[str, Any] = {}
        if writes:
            body["writes"] = writes
        if deletes:
            body["deletes"] = deletes
        return WriteResult.from_dict(
            self._request("POST", f"/v1/fga/stores/{quote(store)}/write", body, idempotency_key)
        )

    def write_tuples(
        self, tuples: List[TupleKey], *, idempotency_key: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> WriteResult:
        """Convenience: write a batch of tuples (no deletes)."""
        return self.write(writes=tuples, idempotency_key=idempotency_key, store_id=store_id)

    def delete_tuples(
        self, tuples: List[TupleKey], *, idempotency_key: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> WriteResult:
        """Convenience: delete a batch of tuples."""
        return self.write(deletes=tuples, idempotency_key=idempotency_key, store_id=store_id)

    def list_objects(
        self,
        *,
        user: str,
        relation: str,
        type: str,  # noqa: A002 - matches the OpenFGA list-objects vocabulary
        authorization_model_id: Optional[str] = None,
        contextual_tuples: Optional[List[TupleKey]] = None,
        store_id: Optional[str] = None,
    ) -> ListObjectsResult:
        """List the objects of a ``type`` a ``user`` has a ``relation`` to."""
        store = self._store(store_id)
        body = self._with_model(
            {
                "user": user,
                "relation": relation,
                "type": type,
                "authorization_model_id": authorization_model_id,
                "contextual_tuples": contextual_tuples,
            }
        )
        body = {k: v for k, v in body.items() if v is not None}
        return ListObjectsResult.from_dict(
            self._request("POST", f"/v1/fga/stores/{quote(store)}/list-objects", body)
        )

    def read(
        self,
        *,
        user: Optional[str] = None,
        relation: Optional[str] = None,
        object: Optional[str] = None,  # noqa: A002
        store_id: Optional[str] = None,
    ) -> ListPage:
        """Query stored tuples by any of user / relation / object."""
        store = self._store(store_id)
        body = {k: v for k, v in {"user": user, "relation": relation, "object": object}.items() if v}
        return ListPage.from_dict(self._request("POST", f"/v1/fga/stores/{quote(store)}/read", body))

    def expand(
        self,
        *,
        object: str,  # noqa: A002
        relation: str,
        authorization_model_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> ExpandResult:
        """Expand the full userset tree for an ``object#relation``."""
        store = self._store(store_id)
        body = self._with_model(
            {"object": object, "relation": relation, "authorization_model_id": authorization_model_id}
        )
        body = {k: v for k, v in body.items() if v is not None}
        return ExpandResult.from_dict(self._request("POST", f"/v1/fga/stores/{quote(store)}/expand", body))

    def batch_check(
        self,
        checks: List[Dict[str, Any]],
        *,
        authorization_model_id: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> BatchCheckResult:
        """Resolve MANY access questions in one round trip (<=100)."""
        store = self._store(store_id)
        body = self._with_model({"checks": checks, "authorization_model_id": authorization_model_id})
        body = {k: v for k, v in body.items() if v is not None}
        return BatchCheckResult.from_dict(
            self._request("POST", f"/v1/fga/stores/{quote(store)}/batch-check", body)
        )

    def store(self, store_id: str) -> "BoundStore":
        """Bind a store id for a scope of calls, OpenFGA-SDK style."""
        return BoundStore(self, store_id)

    # -- stores --

    def list_stores(self) -> ListPage:
        return ListPage.from_dict(self._request("GET", "/v1/fga/stores"))

    def create_store(self, name: str, *, idempotency_key: Optional[str] = None) -> Store:
        d = self._request("POST", "/v1/fga/stores", {"name": name}, idempotency_key)
        return Store(id=d["id"], name=d["name"], created_at=d.get("created_at", 0), updated_at=d.get("updated_at", 0))

    def get_store(self, store_id: str) -> Store:
        d = self._request("GET", f"/v1/fga/stores/{quote(store_id)}")
        return Store(id=d["id"], name=d["name"], created_at=d.get("created_at", 0), updated_at=d.get("updated_at", 0))

    def delete_store(self, store_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/v1/fga/stores/{quote(store_id)}")

    # -- authorization models --

    def list_models(self, store_id: Optional[str] = None) -> ListPage:
        store = self._store(store_id)
        return ListPage.from_dict(
            self._request("GET", f"/v1/fga/stores/{quote(store)}/authorization-models")
        )

    def create_model(
        self,
        type_definitions: List[Any],
        *,
        schema_version: str = "1.1",
        conditions: Optional[Dict[str, Any]] = None,
        store_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AuthorizationModel:
        store = self._store(store_id)
        body: Dict[str, Any] = {"type_definitions": type_definitions, "schema_version": schema_version}
        if conditions is not None:
            body["conditions"] = conditions
        d = self._request("POST", f"/v1/fga/stores/{quote(store)}/authorization-models", body, idempotency_key)
        return AuthorizationModel(
            id=d["id"], store_id=d.get("store_id", store), schema_version=d.get("schema_version", schema_version),
            model=d.get("model"), created_at=d.get("created_at", 0),
        )

    def get_model(self, model_id: str, *, store_id: Optional[str] = None) -> AuthorizationModel:
        store = self._store(store_id)
        d = self._request("GET", f"/v1/fga/stores/{quote(store)}/authorization-models/{quote(model_id)}")
        return AuthorizationModel(
            id=d["id"], store_id=d.get("store_id", store), schema_version=d.get("schema_version", ""),
            model=d.get("model"), created_at=d.get("created_at", 0),
        )


class BoundStore:
    """The store-scoped operations with a fixed store id."""

    def __init__(self, client: AtlasFga, store_id: str) -> None:
        self._c = client
        self._store_id = store_id

    def check(self, **kwargs: Any) -> CheckResult:
        return self._c.check(store_id=self._store_id, **kwargs)

    def write(self, **kwargs: Any) -> WriteResult:
        return self._c.write(store_id=self._store_id, **kwargs)

    def write_tuples(self, tuples: List[TupleKey], **kwargs: Any) -> WriteResult:
        return self._c.write_tuples(tuples, store_id=self._store_id, **kwargs)

    def delete_tuples(self, tuples: List[TupleKey], **kwargs: Any) -> WriteResult:
        return self._c.delete_tuples(tuples, store_id=self._store_id, **kwargs)

    def list_objects(self, **kwargs: Any) -> ListObjectsResult:
        return self._c.list_objects(store_id=self._store_id, **kwargs)

    def read(self, **kwargs: Any) -> ListPage:
        return self._c.read(store_id=self._store_id, **kwargs)

    def expand(self, **kwargs: Any) -> ExpandResult:
        return self._c.expand(store_id=self._store_id, **kwargs)

    def batch_check(self, checks: List[Dict[str, Any]], **kwargs: Any) -> BatchCheckResult:
        return self._c.batch_check(checks, store_id=self._store_id, **kwargs)
