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


class ScriptedTests(unittest.TestCase):
    """Request-shape and response-parsing tests with canned replies."""

    def make(self, *replies: Any) -> Tuple[AtlasFga, List[Dict[str, Any]]]:
        calls: List[Dict[str, Any]] = []
        queue = list(replies)

        def transport(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]) -> Tuple[int, bytes]:
            calls.append({"method": method, "url": url, "body": json.loads(body) if body else None})
            return 200, json.dumps(queue.pop(0)).encode()

        return AtlasFga(secret_key="sk_test", store_id="s1", transport=transport), calls

    def test_condition_context_consistency_on_check(self) -> None:
        fga, calls = self.make(
            {"object": "fga.write_result", "writes": 1, "deletes": 0, "consistency_token": "tok1"},
            {"object": "fga.check", "allowed": True, "authorization_model_id": "m", "consistency_token": "tok2"},
        )
        cond = {"name": "in_window", "context": {"start": "a"}}
        w = fga.write(writes=[{"user": "user:a", "relation": "viewer", "object": "doc:1", "condition": cond}])
        self.assertEqual(calls[0]["body"]["writes"][0]["condition"], cond)
        self.assertEqual(w.consistency_token, "tok1")
        r = fga.check(user="user:a", relation="viewer", object="doc:1", context={"now": "t"},
                      consistency="HIGHER_CONSISTENCY", consistency_token=w.consistency_token)
        self.assertEqual(calls[1]["body"]["context"], {"now": "t"})
        self.assertEqual(calls[1]["body"]["consistency"], "HIGHER_CONSISTENCY")
        self.assertEqual(calls[1]["body"]["consistency_token"], "tok1")
        self.assertEqual(r.consistency_token, "tok2")

    def test_batch_check_and_list_objects_fields(self) -> None:
        fga, calls = self.make(
            {"object": "fga.batch_check", "result": [], "consistency_token": "b"},
            {"object": "fga.list_objects", "objects": [], "consistency_token": "l"},
        )
        res = fga.batch_check([{"user": "u:a", "relation": "v", "object": "d:1", "context": {"x": 1}}],
                              consistency="MINIMIZE_LATENCY")
        self.assertEqual(calls[0]["body"]["checks"][0]["context"], {"x": 1})
        self.assertEqual(calls[0]["body"]["consistency"], "MINIMIZE_LATENCY")
        self.assertEqual(res.consistency_token, "b")
        lo = fga.list_objects(user="u:a", relation="v", type="d", context={"y": 2}, consistency_token="t")
        self.assertEqual(calls[1]["body"]["context"], {"y": 2})
        self.assertEqual(calls[1]["body"]["consistency_token"], "t")
        self.assertEqual(lo.consistency_token, "l")

    def test_list_users_and_all_pages(self) -> None:
        page = lambda users, tok, ex=(): {  # noqa: E731
            "object": "fga.list_users", "users": users, "excluded_users": list(ex),
            "continuation_token": tok, "authorization_model_id": "m", "consistency_token": "c",
        }
        fga, calls = self.make(page(["user:a", "user:*"], "next", ["user:x"]), page(["user:b"], None, ["user:x"]))
        res = fga.list_all_users(object="doc:1", relation="viewer", user_filters=[{"type": "user"}], page_size=2)
        self.assertEqual(calls[0]["url"], "https://api.atlasauth.net/v1/fga/stores/s1/list-users")
        self.assertEqual(calls[0]["body"]["user_filters"], [{"type": "user"}])
        self.assertEqual(calls[0]["body"]["page_size"], 2)
        self.assertNotIn("continuation_token", calls[0]["body"])
        self.assertEqual(calls[1]["body"]["continuation_token"], "next")
        self.assertEqual(res.users, ["user:a", "user:*", "user:b"])
        self.assertEqual(res.excluded_users, ["user:x"])
        self.assertIsNone(res.continuation_token)

    def test_read_changes_and_iter(self) -> None:
        change = lambda op: {  # noqa: E731
            "object": "fga.tuple_change", "operation": op, "user": "user:a", "relation": "viewer",
            "target": "doc:1", "consistency_token": "t", "created_at": 5,
        }
        fga, calls = self.make(
            {"object": "list", "data": [change("write")], "has_more": True, "continuation_token": "c1"},
            {"object": "list", "data": [{**change("delete"), "condition": {"name": "n"}}], "has_more": False,
             "continuation_token": "c2"},
        )
        pages = list(fga.iter_changes(type="doc", page_size=1, start_time="2026-01-01T00:00:00Z"))
        self.assertEqual(calls[0]["method"], "GET")
        self.assertEqual(
            calls[0]["url"],
            "https://api.atlasauth.net/v1/fga/stores/s1/changes?type=doc&page_size=1&start_time=2026-01-01T00%3A00%3A00Z",
        )
        self.assertIn("continuation_token=c1", calls[1]["url"])
        self.assertEqual([p.data[0].operation for p in pages], ["write", "delete"])
        self.assertEqual(pages[1].data[0].condition, {"name": "n"})
        self.assertEqual(pages[1].continuation_token, "c2")


if __name__ == "__main__":
    unittest.main()
