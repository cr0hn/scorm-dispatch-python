# scorm-dispatch-client

> LLM? Read [`llms.txt`](llms.txt) first: a concise manual of every method, error and a full example.

Async Python client for scorm-dispatch, the service that
builds lightweight SCORM packages from a neutral JSON course and, at run time, validates partners by id and
`Origin` and hands out short-lived signed URLs.

- Async only, on `httpx2`. Python 3.14+.
- Fully typed (`py.typed`, mypy strict). Requests are `TypedDict`s, responses are frozen pydantic models.
- Covers the admin API, the public runtime endpoint and the health routes.
- One exception, `ScormDispatchError`, carrying the HTTP status and the RFC 9457 problem body.

## Install

```sh
pip install scorm-dispatch-client
# or straight from git
pip install "scorm-dispatch-client @ git+https://github.com/cr0hn/scorm-dispatch-python"
```

## Quickstart

```python
import asyncio
from scorm_dispatch import Client


async def main() -> None:
    async with Client("https://scorm.example.com", "ADMIN_API_KEY") as sd:
        await sd.put_partner(
            "northwind",
            {
                "name": "Northwind Academy",
                "contactEmail": "learning@northwind.example",
                "seatCap": 500,
                "allowedOrigins": ["https://lms.northwind.example"],
                "active": True,
            },
        )
        await sd.put_asset(
            "vid-walkthrough", {"kind": "video", "uri": "stream-bunny://6f1c2a9e-..."}
        )
        zip_bytes = await sd.create_package(
            "northwind",
            "2004",
            {
                "id": "intro",
                "title": "Intro",
                "version": "1",
                "language": "en",
                "modules": [
                    {
                        "title": "Start",
                        "lessons": [
                            {
                                "id": "l1",
                                "title": "Welcome",
                                "type": "text",
                                "html": "<p>Hello</p>",
                            },
                            {
                                "id": "l2",
                                "title": "Video",
                                "type": "video",
                                "assetKey": "vid-walkthrough",
                            },
                        ],
                    }
                ],
            },
        )
        open("intro.zip", "wb").write(zip_bytes)


asyncio.run(main())
```

## Methods

`Client(base_url, admin_key, *, http_client=None, timeout=30.0)`. Use it as `async with`, or call `aclose()`.

| Method | Route | Returns |
|---|---|---|
| `put_partner(partner_id, partner)` | `PUT /v1/partners/{id}` | `Partner` |
| `get_partner(partner_id)` | `GET /v1/partners/{id}` | `Partner` |
| `list_partners(*, limit=50, offset=0)` | `GET /v1/partners` | `PartnerList` |
| `put_asset(asset_key, asset)` | `PUT /v1/assets/{key}` | `Asset` (has `asset_id`) |
| `get_asset(asset_key)` | `GET /v1/assets/{key}` | `Asset` |
| `create_package(partner_id, scorm_version, course)` | `POST /v1/packages` | `bytes` (the zip) |
| `get_usage_report(month)` | `GET /v1/reports/usage` | `UsageReport` |
| `get_usage_report_csv(month)` | same, `Accept: text/csv` | `str` |
| `get_runtime_asset(asset_id, *, partner, learner, origin)` | `GET /v1/runtime/assets/{id}` | `RuntimeAsset` |
| `healthz()` / `readyz()` | `GET /healthz`, `/readyz` | `None` (raises if not ok) |

Examples of the less obvious ones:

```python
page = await sd.list_partners(limit=100)
for p in page.items:
    print(p.partner_id, p.seat_cap, p.active)

report = await sd.get_usage_report("2026-11")  # month is YYYY-MM
csv_text = await sd.get_usage_report_csv("2026-11")

# What a package does in the browser; useful to check a partner's setup.
# It sends the Origin you pass and never the admin key.
asset = await sd.get_runtime_asset(
    "Zk3p9QwL7xYb2NcVd8TfRa",
    partner="northwind",
    learner="student-1",
    origin="https://lms.northwind.example",
)
print(asset.kind, asset.url, asset.expires_at)
```

## Error handling

Every non-2xx answer raises `ScormDispatchError`:

```python
from scorm_dispatch import ScormDispatchError

try:
    await sd.create_package("northwind", "2004", course)
except ScormDispatchError as e:
    e.status  # int: 400, 401, 403, 404, 409, 413, 422, 429, 5xx
    e.problem  # Problem: type, title, status, detail, errors
    e.field_errors  # 422 only: [FieldError(path="course.modules[0]...", message="...")]
    e.retry_after  # 429 only: seconds, from Retry-After
```

| Status | Meaning |
|---|---|
| 400 | malformed request or parameter |
| 401 | wrong admin key |
| 403 | runtime: partner unknown/inactive or `Origin` not allowed |
| 404 | partner, asset or runtime asset not found |
| 409 | asset `kind` cannot change |
| 413 | package body above the server's limit |
| 422 | validation failed; see `field_errors` |
| 429 | rate limit; wait `retry_after` seconds |

A non-problem body (for example a proxy's HTML page) still raises, with the text in `problem.detail`.
Network failures are `httpx2` exceptions and are not wrapped.

## Timeouts and retries

`timeout` (seconds, default 30) applies to every request. **The client never retries**: `PUT` upserts are
idempotent and safe for you to retry; `POST /v1/packages` is a pure function of its body, also safe.
Back off on 429 using `retry_after`. To tune pooling or add transport-level retries, pass your own
`httpx2.AsyncClient` as `http_client` (you then own and close it).

## Typing

Request bodies are `TypedDict`s with the wire (camelCase) keys: your type checker catches typos and wrong
lesson shapes. Responses are frozen pydantic models with snake_case attributes and parsed datetimes.
Unknown response fields are ignored, so a newer server does not break an older client.

## Versioning and compatibility

The client follows semantic versioning. It is built and tested against the contract in
[`spec/openapi.yaml`](spec/openapi.yaml) (API 1.x); a 1.x server is expected to work with any 0.x/1.x client.
Contract tests validate every request and response against that file.

## Development

```sh
make check          # lint, mypy, unit (100% line+branch coverage), contract, integration
make integration    # needs Docker, Go, and the server source: SCORM_DISPATCH_SRC=../scorm-dispatch
```

The integration suite builds the real server, starts Postgres behind PgBouncer and MinIO with
testcontainers, and runs every public method and documented error status against it. It fails, not skips,
if the server source is missing.

## Contributing

Issues and pull requests welcome. Keep `make check` green; a change in behaviour needs a unit test and an
integration test. When the server API changes, copy its `api/openapi.yaml` to `spec/openapi.yaml`.

## Security

Report vulnerabilities privately to me@danielalfocea.com. Never put the admin key in a browser: this client
is for server-side use. Runtime calls are made by packages in browsers, not by this client in production.

## License

MIT, see [LICENSE](LICENSE).
