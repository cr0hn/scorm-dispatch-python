"""Exact requests the client builds and how it maps answers, against a MockTransport."""

import json
from collections.abc import Callable

import httpx2
import pytest

from scorm_dispatch import Client, ScormDispatchError
from tests.samples import (
    ASSET_OUT,
    COURSE,
    PARTNER_IN,
    PARTNER_OUT,
    PROBLEM_422,
    REPORT_OUT,
    RUNTIME_OUT,
)

BASE = "https://sd.test"
Handler = Callable[[httpx2.Request], httpx2.Response]


def make(handler: Handler) -> tuple[Client, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    return Client(BASE, "k3y", http_client=http), seen


def js(body: object, status: int = 200, headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, json=body, headers=headers)


async def test_put_partner() -> None:
    c, seen = make(lambda _: js(PARTNER_OUT, 201))
    p = await c.put_partner("northwind", PARTNER_IN)
    r = seen[0]
    assert (r.method, str(r.url)) == ("PUT", BASE + "/v1/partners/northwind")
    assert r.headers["Authorization"] == "Bearer k3y"
    assert json.loads(r.content) == PARTNER_IN
    assert p.partner_id == "northwind" and p.allowed_origins == PARTNER_IN["allowedOrigins"]


async def test_get_and_list_partners() -> None:
    c, seen = make(
        lambda r: js(
            {"items": [PARTNER_OUT], "total": 1} if r.url.path.endswith("s") else PARTNER_OUT
        )
    )
    assert (await c.get_partner("northwind")).name == "Northwind Academy"
    page = await c.list_partners(limit=1, offset=2)
    assert page.total == 1
    assert seen[0].method == "GET" and seen[0].url.path == "/v1/partners/northwind"
    assert dict(seen[1].url.params) == {"limit": "1", "offset": "2"}


async def test_assets() -> None:
    c, seen = make(lambda _: js(ASSET_OUT))
    a = await c.put_asset("vid-walkthrough", {"kind": "video", "uri": ASSET_OUT["uri"]})
    await c.get_asset("vid-walkthrough")
    assert a.asset_id == "Zk3p9QwL7xYb2NcVd8TfRa"
    assert [(r.method, r.url.path) for r in seen] == [
        ("PUT", "/v1/assets/vid-walkthrough"),
        ("GET", "/v1/assets/vid-walkthrough"),
    ]
    assert json.loads(seen[0].content) == {"kind": "video", "uri": ASSET_OUT["uri"]}


async def test_create_package_returns_zip_bytes() -> None:
    zip_bytes = b"PK\x03\x04fake"
    c, seen = make(
        lambda _: httpx2.Response(
            200, content=zip_bytes, headers={"Content-Type": "application/zip"}
        )
    )
    assert await c.create_package("northwind", "2004", COURSE) == zip_bytes
    assert json.loads(seen[0].content) == {
        "partnerId": "northwind",
        "scormVersion": "2004",
        "course": COURSE,
    }
    assert seen[0].url.path == "/v1/packages" and seen[0].method == "POST"


async def test_usage_report_json_and_csv() -> None:
    def handler(r: httpx2.Request) -> httpx2.Response:
        if r.headers.get("Accept") == "text/csv":
            return httpx2.Response(
                200, text="partner_id\nnorthwind\n", headers={"Content-Type": "text/csv"}
            )
        return js(REPORT_OUT)

    c, seen = make(handler)
    rep = await c.get_usage_report("2026-11")
    assert rep.partners[0].rejected_origins[0].count == 4
    assert (await c.get_usage_report_csv("2026-11")).startswith("partner_id")
    assert dict(seen[0].url.params) == {"month": "2026-11"}
    assert seen[1].headers["Accept"] == "text/csv"


async def test_runtime_sends_origin_and_never_the_admin_key() -> None:
    c, seen = make(lambda _: js(RUNTIME_OUT))
    a = await c.get_runtime_asset(
        "Zk3p9QwL7xYb2NcVd8TfRa",
        partner="northwind",
        learner="s 1",
        origin="https://lms.northwind.example",
    )
    r = seen[0]
    assert r.headers["Origin"] == "https://lms.northwind.example"
    assert "Authorization" not in r.headers
    assert dict(r.url.params) == {"partner": "northwind", "learner": "s 1"}
    assert a.kind == "video"


async def test_health_routes_are_public() -> None:
    c, seen = make(lambda _: js({"status": "ok"}))
    await c.healthz()
    await c.readyz()
    assert [r.url.path for r in seen] == ["/healthz", "/readyz"]
    assert all("Authorization" not in r.headers for r in seen)


@pytest.mark.parametrize("status", [400, 401, 404, 409, 422, 429])
async def test_error_mapping(status: int) -> None:
    body = (
        PROBLEM_422
        if status == 422
        else {"type": "about:blank", "title": "T", "status": status, "detail": "d"}
    )
    headers = {"Retry-After": "7"} if status == 429 else None
    c, _ = make(lambda _: js(body, status, headers))
    with pytest.raises(ScormDispatchError) as e:
        await c.get_partner("x")
    assert e.value.status == status
    assert e.value.problem.status == status
    assert e.value.retry_after == (7 if status == 429 else None)
    assert [f.path for f in e.value.field_errors] == (
        ["course.modules[0].lessons[1].assetKey"] if status == 422 else []
    )


async def test_non_problem_error_body() -> None:
    c, _ = make(lambda _: httpx2.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(ScormDispatchError) as e:
        await c.healthz()
    assert e.value.status == 502 and "bad gateway" in (e.value.problem.detail or "")


async def test_path_segments_are_quoted() -> None:
    c, seen = make(lambda _: js(PARTNER_OUT))
    await c.get_partner("a/b")
    assert seen[0].url.raw_path == b"/v1/partners/a%2Fb"


async def test_injected_client_is_not_closed() -> None:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: js({"status": "ok"})))
    async with Client(BASE, "k", http_client=http) as c:
        await c.healthz()
    assert not http.is_closed
    await http.aclose()


async def test_owned_client_is_closed() -> None:
    async with Client(BASE, "k") as c:
        inner = c._http
    assert inner.is_closed
