"""End-to-end tests against an in-memory fake of the Atlas /v1/fga surface.

A fake Transport implements just enough of the wire contract (paths + response
envelopes) to exercise the client without a live server. Runs under plain
``python -m unittest`` — no third-party test deps.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from atlas_fga import AtlasFga, AtlasFgaError


class FakeAtlas:
    """A tiny stand-in for the Atlas FGA backend. Records captured requests."""

    def __init__(self) -> None:
        self.tuples: set[str] = set()  # "user|relation|object"
        self.calls: List[Dict[str, Any]] = []

    @staticmethod
    def _key(t: Dict[str, str]) -> str:
        return f"{t['user']}|{t['relation']}|{t['object']}"

    def transport(
        self, method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
    ) -> Tuple[int, bytes]:
        path = urlparse(url).path
        payload = json.loads(body) if body else {}
        self.calls.append({"method": method, "url": url, "headers": headers, "body": payload})

        def ok(obj: Any, status: int = 200) -> Tuple[int, bytes]:
            return status, json.dumps(obj).encode()

        if "/stores/missing/" in path:
            return 404, json.dumps(
                {"errors": [{"code": "store_id_not_found", "message": "Unknown FGA store."}]}
            ).encode()

        if method == "POST" and path.endswith("/check"):
            allowed = self._key(payload) in self.tuples
            return ok({"object": "fga.check", "allowed": allowed, "authorization_model_id": "model_1"})
        if method == "POST" and path.endswith("/write"):
            writes = payload.get("writes", [])
            deletes = payload.get("deletes", [])
            for t in writes:
                self.tuples.add(self._key(t))
            for t in deletes:
                self.tuples.discard(self._key(t))
            return ok({"object": "fga.write_result", "writes": len(writes), "deletes": len(deletes)})
        if method == "POST" and path.endswith("/list-objects"):
            objs = [
                k.split("|")[2]
                for k in self.tuples
                if k.split("|")[0] == payload["user"]
                and k.split("|")[1] == payload["relation"]
                and k.split("|")[2].startswith(payload["type"] + ":")
            ]
            return ok({"object": "fga.list_objects", "objects": objs, "authorization_model_id": "model_1"})
        if method == "POST" and path.endswith("/read"):
            data = []
            for k in self.tuples:
                u, r, o = k.split("|")
                if (
                    (not payload.get("user") or u == payload["user"])
                    and (not payload.get("relation") or r == payload["relation"])
                    and (not payload.get("object") or o == payload["object"])
                ):
                    data.append({"object": "fga.tuple", "user": u, "relation": r, "target": o, "created_at": 1})
            return ok({"object": "list", "data": data, "has_more": False})
        return 404, json.dumps({"errors": [{"code": "not_found", "message": path}]}).encode()


class AtlasFgaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeAtlas()

    def client(self, **kw: Any) -> AtlasFga:
        return AtlasFga(secret_key="sk_test", transport=self.fake.transport, **kw)

    def test_auth_and_base_url(self) -> None:
        fga = self.client(store_id="store_1")
        fga.check(user="user:a", relation="viewer", object="doc:1")
        call = self.fake.calls[0]
        self.assertEqual(call["url"], "https://api.atlasauth.net/v1/fga/stores/store_1/check")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk_test")

    def test_write_then_check(self) -> None:
        fga = self.client(store_id="store_1")
        self.assertFalse(fga.check(user="user:alice", relation="viewer", object="doc:readme").allowed)
        res = fga.write_tuples([{"user": "user:alice", "relation": "viewer", "object": "doc:readme"}])
        self.assertEqual(res.writes, 1)
        self.assertTrue(fga.check(user="user:alice", relation="viewer", object="doc:readme").allowed)

    def test_list_objects_round_trip(self) -> None:
        fga = self.client()
        store = fga.store("store_1")
        store.write_tuples(
            [
                {"user": "user:bob", "relation": "editor", "object": "doc:1"},
                {"user": "user:bob", "relation": "editor", "object": "doc:2"},
                {"user": "user:bob", "relation": "editor", "object": "folder:x"},
            ]
        )
        res = store.list_objects(user="user:bob", relation="editor", type="doc")
        self.assertEqual(sorted(res.objects), ["doc:1", "doc:2"])

    def test_read_envelope(self) -> None:
        fga = self.client(store_id="store_1")
        fga.write_tuples([{"user": "user:x", "relation": "owner", "object": "doc:9"}])
        page = fga.read(object="doc:9")
        self.assertEqual(page.object, "list")
        self.assertFalse(page.has_more)
        self.assertEqual(page.data[0]["target"], "doc:9")

    def test_default_model_folded(self) -> None:
        fga = self.client(store_id="store_1", authorization_model_id="model_pinned")
        fga.check(user="user:a", relation="viewer", object="doc:1")
        self.assertEqual(self.fake.calls[0]["body"]["authorization_model_id"], "model_pinned")

    def test_error_envelope(self) -> None:
        fga = self.client()
        with self.assertRaises(AtlasFgaError) as ctx:
            fga.check(user="u:a", relation="v", object="d:1", store_id="missing")
        self.assertEqual(ctx.exception.code, "store_id_not_found")
        self.assertEqual(ctx.exception.status, 404)

    def test_missing_store(self) -> None:
        fga = self.client()
        with self.assertRaises(ValueError):
            fga.check(user="u:a", relation="v", object="d:1")

    def test_requires_secret_key(self) -> None:
        with self.assertRaises(ValueError):
            AtlasFga(transport=self.fake.transport)


if __name__ == "__main__":
    unittest.main()
