"""The client against the real server: every public method and every documented error status."""

import io
import uuid
import zipfile
from collections.abc import Awaitable
from datetime import UTC, datetime

import pytest

from scorm_dispatch import Client, ScormDispatchError
from scorm_dispatch.models import Course, PartnerInput, ScormVersion
from tests.conftest import LEARNER_RATE, Server
from tests.samples import COURSE

pytestmark = pytest.mark.integration

ORIGIN = "https://lms.northwind.example"


def uid() -> str:
    return "t" + uuid.uuid4().hex[:10]


async def status_of(coro: Awaitable[object]) -> ScormDispatchError:
    with pytest.raises(ScormDispatchError) as e:
        await coro
    return e.value


async def test_full_flow(client: Client) -> None:
    pid, vid, doc = uid(), uid(), uid()
    await client.healthz()
    await client.readyz()

    partner = await client.put_partner(
        pid,
        {
            "name": "Northwind",
            "contactEmail": "ops@northwind.example",
            "seatCap": 5,
            "allowedOrigins": [ORIGIN],
            "active": True,
        },
    )
    assert partner.partner_id == pid
    assert (await client.get_partner(pid)).name == "Northwind"
    assert pid in [p.partner_id for p in (await client.list_partners(limit=200)).items]

    video = await client.put_asset(vid, {"kind": "video", "uri": "stream-bunny://guid-1"})
    again = await client.put_asset(vid, {"kind": "video", "uri": "stream-bunny://guid-2"})
    assert again.asset_id == video.asset_id  # opaque id never changes
    file = await client.put_asset(doc, {"kind": "file", "uri": "s3://bucket/doc.pdf"})
    assert (await client.get_asset(doc)).asset_id == file.asset_id

    course: Course = {
        "id": "c1",
        "title": "Course",
        "version": "1",
        "language": "en",
        "modules": [
            {
                "title": "M",
                "lessons": [
                    {"id": "l1", "title": "Text", "type": "text", "html": "<p>Hi</p>"},
                    {"id": "l2", "title": "Video", "type": "video", "assetKey": vid},
                    {
                        "id": "l3",
                        "title": "File",
                        "type": "file",
                        "assetKey": doc,
                        "fileName": "d.pdf",
                    },
                    COURSE["modules"][0]["lessons"][3],
                ],
            }
        ],
    }
    versions: list[ScormVersion] = ["1.2", "2004"]
    for version in versions:
        data = await client.create_package(pid, version, course)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert "imsmanifest.xml" in names

    learner = uid()
    ra = await client.get_runtime_asset(video.asset_id, partner=pid, learner=learner, origin=ORIGIN)
    assert ra.kind == "video" and ra.url
    rf = await client.get_runtime_asset(file.asset_id, partner=pid, learner=learner, origin=ORIGIN)
    assert rf.kind == "file"
    refused = await status_of(
        client.get_runtime_asset(
            video.asset_id, partner=pid, learner=learner, origin="https://evil.example"
        )
    )
    assert refused.status == 403

    month = datetime.now(UTC).strftime("%Y-%m")
    report = await client.get_usage_report(month)
    row = next(p for p in report.partners if p.partner_id == pid)
    assert row.active_learners == 1
    assert [(o.origin, o.count) for o in row.rejected_origins] == [("https://evil.example", 1)]
    csv = await client.get_usage_report_csv(month)
    assert csv.startswith("partner_id,partner_name,seat_cap,active_learners,rejected_origins")
    assert pid in csv


async def test_error_statuses(client: Client, server: Server) -> None:
    pid, key = uid(), uid()
    ok_partner: PartnerInput = {
        "name": "P",
        "contactEmail": "p@example.com",
        "seatCap": 1,
        "allowedOrigins": [ORIGIN],
        "active": True,
    }
    await client.put_partner(pid, ok_partner)
    asset = await client.put_asset(key, {"kind": "file", "uri": "s3://bucket/x.pdf"})

    # 401: wrong key
    async with Client(server.base_url, "wrong") as bad:
        e = await status_of(bad.list_partners())
        assert e.status == 401

    # 400: malformed parameter
    assert (await status_of(client.get_usage_report("2026-13"))).status == 400
    # 404: unknown partner / asset / runtime asset
    assert (await status_of(client.get_partner(uid()))).status == 404
    assert (await status_of(client.get_asset(uid()))).status == 404
    assert (await status_of(client.create_package(uid(), "2004", COURSE))).status == 404
    unknown = "A" * 22
    assert (
        await status_of(client.get_runtime_asset(unknown, partner=pid, learner="l", origin=ORIGIN))
    ).status == 404
    # 409: asset kind cannot change
    assert (
        await status_of(client.put_asset(key, {"kind": "video", "uri": "s3://bucket/x.pdf"}))
    ).status == 409
    # 422: unregistered assetKey, with field errors
    e = await status_of(client.create_package(pid, "2004", COURSE))
    assert e.status == 422 and e.field_errors and "assetKey" in e.field_errors[0].path
    # 413: body over MAX_PACKAGE_BYTES
    big: Course = {
        "id": "big",
        "title": "Big",
        "version": "1",
        "language": "en",
        "modules": [
            {
                "title": "M",
                "lessons": [{"id": "l1", "title": "T", "type": "text", "html": "x" * 30_000}],
            }
        ],
    }
    assert (await status_of(client.create_package(pid, "2004", big))).status == 413
    # 429: per learner rate limit
    learner = uid()
    last: ScormDispatchError | None = None
    for _ in range(LEARNER_RATE + 2):
        try:
            await client.get_runtime_asset(
                asset.asset_id, partner=pid, learner=learner, origin=ORIGIN
            )
        except ScormDispatchError as err:
            last = err
            break
    assert last is not None and last.status == 429 and last.retry_after is not None
