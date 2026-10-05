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
| `expand(object=, relation=)` | `POST /v1/fga/stores/:store/expand` |
| `list_stores` / `create_store` / `get_store` / `delete_store` | `/v1/fga/stores` |
| `list_models` / `create_model` / `get_model` | `/v1/fga/stores/:store/authorization-models` |

`fga.store("store_id")` returns a `BoundStore` with the store id fixed, for the
common single-store case.

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
