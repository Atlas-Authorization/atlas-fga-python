# atlas-fga

The Atlas **FGA** (fine-grained, relationship-based authorization — Zanzibar /
OpenFGA) client for Python. Native, standard-library-only, preconfigured for
Atlas.

```bash
pip install atlas-fga
```

## Quickstart

```python
from atlas_fga import AtlasFga

fga = AtlasFga(secret_key="sk_live_...", store_id="store_123")

# write a relationship tuple
fga.write_tuples([{"user": "user:alice", "relation": "viewer", "object": "doc:readme"}])

# ask an access question
fga.check(user="user:alice", relation="viewer", object="doc:readme").allowed  # True

# list the objects a user can reach
fga.list_objects(user="user:alice", relation="viewer", type="doc").objects  # ['doc:readme']
```

Configuration falls back to the environment when not passed: `ATLAS_SECRET_KEY`,
`ATLAS_FGA_STORE_ID`, `ATLAS_FGA_MODEL_ID`, and `ATLAS_FGA_URL` (base URL,
default `https://api.atlasauth.net`). So `AtlasFga()` works when those are set.

## Operations

| Method | Atlas route |
| --- | --- |
| `check(user=, relation=, object=)` | `POST /v1/fga/stores/:store/check` |
| `batch_check(checks)` | `POST /v1/fga/stores/:store/batch-check` |
| `write(writes=, deletes=)` / `write_tuples(...)` / `delete_tuples(...)` | `POST /v1/fga/stores/:store/write` |
| `read(user=, relation=, object=)` | `POST /v1/fga/stores/:store/read` |
| `list_objects(user=, relation=, type=)` | `POST /v1/fga/stores/:store/list-objects` |
| `list_users(object=, relation=, user_filters=)` / `list_all_users(...)` | `POST /v1/fga/stores/:store/list-users` |
| `read_changes(type=, page_size=, continuation_token=, start_time=)` / `iter_changes(...)` | `GET /v1/fga/stores/:store/changes` |
| `expand(object=, relation=)` | `POST /v1/fga/stores/:store/expand` |
| `list_stores` / `create_store` / `get_store` / `delete_store` | `/v1/fga/stores` |
| `list_models` / `create_model` / `get_model` | `/v1/fga/stores/:store/authorization-models` |

`fga.store("store_id")` returns a `BoundStore` with the store id fixed, for the
common single-store case.

## Conditions and context

A tuple may carry a `condition` (`{"name": ..., "context": {...}}`, context
optional); the model declares them in a top-level `conditions` map passed to
`create_model(..., conditions=...)`:

```python
fga.create_model(
    type_definitions,
    conditions={
        "in_window": {
            "expression": "request_time < expires",
            "parameters": {
                "request_time": {"type_name": "TYPE_NAME_TIMESTAMP"},
                "expires": {"type_name": "TYPE_NAME_TIMESTAMP"},
            },
        }
    },
)
fga.write_tuples([{
    "user": "user:alice", "relation": "viewer", "object": "doc:readme",
    "condition": {"name": "in_window", "context": {"expires": "2027-01-01T00:00:00Z"}},
}])
fga.check(user="user:alice", relation="viewer", object="doc:readme",
          context={"request_time": "2026-10-27T00:00:00Z"}).allowed
```

`context` (request-time values for condition parameters) is accepted by
`check`, `list_objects`, `list_users`, and on each item of `batch_check`.
Tuples returned by `read` and the changes feed include `condition` only when
they have one.

## Consistency

`check`, `batch_check`, `list_objects` and `list_users` accept `consistency`
(`"UNSPECIFIED"`, `"MINIMIZE_LATENCY"`, `"HIGHER_CONSISTENCY"`) and
`consistency_token`. `MINIMIZE_LATENCY` (the default) may be served from a
short-lived cache; `HIGHER_CONSISTENCY` bypasses it. Every write and read
result carries a `consistency_token`; pass the token from a write to guarantee
the read reflects at least that write, e.g. right after revoking access:

```python
w = fga.delete_tuples([{"user": "user:alice", "relation": "viewer", "object": "doc:readme"}])
fga.check(user="user:alice", relation="viewer", object="doc:readme",
          consistency_token=w.consistency_token).allowed  # False
```

## Listing users and following changes

```python
res = fga.list_users(object="doc:readme", relation="viewer", user_filters=[{"type": "user"}])
res.users            # "user:alice", a userset "team:eng#member", or a wildcard "user:*"
res.excluded_users   # ids a wildcard does not cover
fga.list_all_users(object="doc:readme", relation="viewer", user_filters=[{"type": "user"}])  # all pages

page = fga.read_changes(type="doc", page_size=50)
for page in fga.iter_changes(type="doc"):        # until has_more is false
    for c in page.data:
        print(c.operation, c.user, c.relation, c.target)
# keep page.continuation_token (returned even on the last page) and pass it
# later as continuation_token= to receive only newer changes.
```

`user_filters` takes exactly one `{"type": ..., "relation"?: ...}`; `page_size`
is 1-1000 for `list_users` (default 1000) and 1-100 for `read_changes`
(default 50); `start_time` is RFC 3339.

## Errors

Non-2xx responses raise `AtlasFgaError` carrying Atlas's `{"errors": [...]}`
envelope:

```python
from atlas_fga import AtlasFgaError
try:
    fga.check(user="user:a", relation="viewer", object="doc:1")
except AtlasFgaError as e:
    if e.code == "store_id_not_found":
        ...
```

## Relationship to OpenFGA

Atlas's engine is **OpenFGA-shaped** (same model DSL/JSON, same tuple
vocabulary, same operations) and also exposes an OpenFGA **wire-compatible**
mirror at `/v1/openfga` that the stock `openfga-sdk` can drive for
`check` / `write` / stores / models (configure its `api_url` to
`https://<host>/v1/openfga` and the credential as the Atlas secret key).

This client targets the **native `/v1/fga` surface** because `list-objects`,
`read`, and `expand` live only there (not on `/v1/openfga`), and `/v1/fga` wraps
responses in Atlas's `{"object": ...}` envelope — `read` returns a `ListPage`
(`{"object":"list", "data", "has_more"}`) with each tuple's object named
`target`, rather than OpenFGA's `{"tuples", "continuation_token"}`. Auth is an
Atlas secret key (`Authorization: Bearer sk_…`, scopes `fga:read`/`fga:write`),
not an OpenFGA store-scoped token. Model format and tuple semantics are
identical to OpenFGA.

## Development

```bash
python -m unittest discover -s tests -v   # no third-party deps required
```
