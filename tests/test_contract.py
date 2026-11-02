"""Every request the client builds and every response it parses is checked against the spec."""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.parse import parse_qsl

import httpx2
import pytest
from openapi_core import Config, OpenAPI
from openapi_core.exceptions import OpenAPIError
from openapi_core.testing import MockRequest, MockResponse

from scorm_dispatch import Client, ScormDispatchError
from scorm_dispatch.models import Course, PartnerInput
from tests.samples import (
    ASSET_OUT,
    COURSE,
    PARTNER_IN,
    PARTNER_OUT,
    PROBLEM_422,
    REPORT_OUT,
    RUNTIME_OUT,
)

SPEC = Path(__file__).parent.parent / "spec" / "openapi.yaml"
HOST = "https://scorm.mycompany.test"  # the spec's server

api = OpenAPI.from_file_path(
    str(SPEC),
    config=Config(
        extra_media_type_deserializers={
            "application/problem+json": json.loads,
            "text/csv": lambda raw: raw.decode(),
        }
    ),
)

Reply = tuple[int, str, bytes]  # status, content type, body


def check_request(request: httpx2.Request) -> None:
    mock = MockRequest(
        HOST,
        request.method.lower(),
        request.url.path,
        args=dict(parse_qsl(request.url.query.decode())),
        headers={k: v for k, v in request.headers.items() if k.lower() not in {"host"}},
        data=request.content,
        content_type=request.headers.get("content-type", "application/json").split(";")[0],
    )
    api.validate_request(mock)


def check_response(request: httpx2.Request, reply: Reply) -> None:
    status, ctype, body = reply
    mock_req = MockRequest(
        HOST,
        request.method.lower(),
        request.url.path,
        args=dict(parse_qsl(request.url.query.decode())),
        headers=dict(request.headers),
        data=request.content,
        content_type=request.headers.get("content-type", "application/json").split(";")[0],
    )
    extra = {"Retry-After": "3"} if status == 429 else {}
    api.validate_response(
        mock_req, MockResponse(body, status_code=status, headers=extra, content_type=ctype)
    )


def j(body: object, status: int = 200) -> Reply:
    ctype = "application/json" if status < 400 else "application/problem+json"
    return status, ctype, json.dumps(body).encode()


def client_for(route: Callable[[httpx2.Request], Reply]) -> Client:
    def handler(request: httpx2.Request) -> httpx2.Response:
        check_request(request)
        reply = route(request)
        check_response(request, reply)
        return httpx2.Response(reply[0], content=reply[2], headers={"Content-Type": reply[1]})

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return Client(HOST, "k3y", http_client=http)


async def test_every_operation_matches_the_spec() -> None:
    def route(r: httpx2.Request) -> Reply:
        p = r.url.path
        if p == "/v1/partners":
            return j({"items": [PARTNER_OUT], "total": 1})
        if p.startswith("/v1/partners/"):
            return j(PARTNER_OUT, 201 if r.method == "PUT" else 200)
        if p.startswith("/v1/assets/"):
            return j(ASSET_OUT, 201 if r.method == "PUT" else 200)
        if p == "/v1/packages":
            return 200, "application/zip", b"PK\x03\x04"
        if p == "/v1/reports/usage":
            if r.headers.get("accept") == "text/csv":
                return 200, "text/csv", b"partner_id,partner_name\nnorthwind,N\n"
            return j(REPORT_OUT)
        if p.startswith("/v1/runtime/"):
            return j(RUNTIME_OUT)
        return j({"status": "ok"})

    c = client_for(route)
    await c.put_partner("northwind", PARTNER_IN)
    await c.get_partner("northwind")
    await c.list_partners(limit=10, offset=0)
    await c.put_asset("vid-walkthrough", {"kind": "video", "uri": ASSET_OUT["uri"]})
    await c.get_asset("vid-walkthrough")
    await c.create_package("northwind", "1.2", COURSE)
    await c.get_usage_report("2026-11")
    await c.get_usage_report_csv("2026-11")
    await c.get_runtime_asset(
        "Zk3p9QwL7xYb2NcVd8TfRa",
        partner="northwind",
        learner="s-1",
        origin="https://lms.northwind.example",
    )
    await c.healthz()
    await c.readyz()


@pytest.mark.parametrize(
    ("status", "body"),
    [(422, PROBLEM_422), (429, {"type": "about:blank", "title": "T", "status": 429})],
)
async def test_error_bodies_match_the_spec(status: int, body: dict[str, object]) -> None:
    c = client_for(lambda _: j(body, status))
    with pytest.raises(ScormDispatchError):
        await c.put_partner("northwind", PARTNER_IN)


async def test_extra_request_field_is_caught() -> None:
    """Guard of the guard: a field the spec does not have must make the contract fail."""
    bad = cast(Course, {**copy.deepcopy(COURSE), "surprise": True})
    c = client_for(lambda _: (200, "application/zip", b"PK"))
    with pytest.raises(OpenAPIError, match=r"(?i)additional properties"):
        await c.create_package("northwind", "2004", bad)


async def test_extra_partner_field_is_caught() -> None:
    c = client_for(lambda _: j(PARTNER_OUT, 201))
    with pytest.raises(OpenAPIError, match=r"(?i)additional properties"):
        await c.put_partner("northwind", cast(PartnerInput, {**PARTNER_IN, "surprise": 1}))
