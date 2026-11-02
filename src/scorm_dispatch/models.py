"""Typed bodies of the scorm-dispatch API.

Requests are TypedDicts with the wire (camelCase) keys, so a literal reads like the docs.
Responses are frozen pydantic models: they validate what the server sent and expose
snake_case attributes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

AssetKind = Literal["video", "file"]
ScormVersion = Literal["1.2", "2004"]


# --- request bodies -------------------------------------------------------------------------


class PartnerInput(TypedDict):
    """Body of `put_partner`; replaces every field of the partner."""

    name: str
    contactEmail: str
    seatCap: int
    allowedOrigins: list[str]
    active: bool


class AssetInput(TypedDict):
    """Body of `put_asset`; `kind` cannot change once the asset exists."""

    kind: AssetKind
    uri: str


class Option(TypedDict):
    """One answer option of a question."""

    id: str
    html: str


class Question(TypedDict):
    """A `single` (one correct option) or `multiple` choice question."""

    id: str
    type: Literal["single", "multiple"]
    promptHtml: str
    options: list[Option]
    correct: list[str]


class Quiz(TypedDict):
    """A quiz lesson body; at most one quiz per course may be `final`."""

    final: bool
    passingScore: int
    questions: list[Question]


class TextLesson(TypedDict):
    """Lesson with sanitised HTML."""

    id: str
    title: str
    type: Literal["text"]
    html: str


class VideoLesson(TypedDict):
    """Lesson that plays a registered video asset."""

    id: str
    title: str
    type: Literal["video"]
    assetKey: str


class FileLesson(TypedDict):
    """Lesson that offers a registered file asset."""

    id: str
    title: str
    type: Literal["file"]
    assetKey: str
    fileName: str


class QuizLesson(TypedDict):
    """Lesson that holds a quiz."""

    id: str
    title: str
    type: Literal["quiz"]
    quiz: Quiz


Lesson = TextLesson | VideoLesson | FileLesson | QuizLesson


class Module(TypedDict):
    """A titled group of lessons."""

    title: str
    lessons: list[Lesson]


class Course(TypedDict):
    """The neutral course format sent to `create_package`."""

    id: str
    title: str
    version: str
    language: str
    modules: list[Module]


class PackageRequest(TypedDict):
    """Body of `POST /v1/packages`."""

    partnerId: str
    scormVersion: ScormVersion
    course: Course


# --- responses ------------------------------------------------------------------------------


class _Response(BaseModel):
    # Unknown fields are ignored: a newer server must not break an older client.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)


class Partner(_Response):
    """A content partner as stored by the server."""

    partner_id: str
    name: str
    contact_email: str
    seat_cap: int
    allowed_origins: list[str]
    active: bool
    created_at: datetime
    updated_at: datetime


class PartnerList(_Response):
    """One page of partners and the total count."""

    items: list[Partner]
    total: int


class Asset(_Response):
    """A registered video or file; `asset_id` is opaque and stable."""

    asset_key: str
    asset_id: str
    kind: AssetKind
    uri: str
    created_at: datetime
    updated_at: datetime


class RuntimeAsset(_Response):
    """Short-lived signed URL for an asset."""

    kind: AssetKind
    url: str
    expires_at: datetime


class RejectedOrigin(_Response):
    """An origin refused by the runtime and how many times."""

    origin: str
    count: int


class PartnerUsage(_Response):
    """Usage of one partner in one month."""

    partner_id: str
    name: str
    seat_cap: int
    active_learners: int
    rejected_origins: list[RejectedOrigin]


class UsageReport(_Response):
    """Active learners per partner for one month."""

    month: str
    partners: list[PartnerUsage]


class FieldError(_Response):
    """One validation problem and the path of the offending field."""

    path: str
    message: str


class Problem(_Response):
    """RFC 9457 body. `errors` is present on 422 only."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None


__all__ = [
    "Asset",
    "AssetInput",
    "AssetKind",
    "Course",
    "FieldError",
    "FileLesson",
    "Lesson",
    "Module",
    "Option",
    "PackageRequest",
    "Partner",
    "PartnerInput",
    "PartnerList",
    "PartnerUsage",
    "Problem",
    "Question",
    "Quiz",
    "QuizLesson",
    "RejectedOrigin",
    "RuntimeAsset",
    "ScormVersion",
    "TextLesson",
    "UsageReport",
    "VideoLesson",
]
