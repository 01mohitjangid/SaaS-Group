"""Request and response shapes for the CMS.

Validation that an editor can hit lives in these models, so the error comes back with
a field name the form can highlight. Rules that need the whole catalogue — artwork
present, a section on a published show, one variant per language — cannot be checked
here and live in `app.domain.rules` instead.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["draft", "published"]
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ShowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, Field(min_length=1, max_length=160)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    synopsis: Annotated[str, Field(max_length=4000)] = ""
    section: str | None = None
    categories: list[str] = Field(default_factory=list)
    status: Status = "draft"

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        if not SLUG.match(value):
            raise ValueError(
                "Use lower-case letters, numbers and hyphens only, for example 'moti-and-friends'."
            )
        return value


class ShowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    synopsis: Annotated[str, Field(max_length=4000)] | None = None
    section: str | None = None
    categories: list[str] | None = None
    status: Status | None = None


class SeasonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_number: Annotated[int, Field(ge=0, le=99)]
    title: str | None = None


class EpisodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season_number: Annotated[int, Field(ge=0, le=99)]
    episode_number: Annotated[int, Field(ge=0, le=999)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    duration_seconds: Annotated[int, Field(gt=0, le=86_400)] | None = None
    language: Annotated[str, Field(min_length=2, max_length=8)]
    content_group: Annotated[str, Field(min_length=1, max_length=160)]
    status: Status = "draft"
    external_id: str | None = None


class EpisodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_number: Annotated[int, Field(ge=0, le=999)] | None = None
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    duration_seconds: Annotated[int, Field(gt=0, le=86_400)] | None = None
    language: Annotated[str, Field(min_length=2, max_length=8)] | None = None
    content_group: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    status: Status | None = None


class ArtworkOut(BaseModel):
    id: uuid.UUID
    kind: str
    url: str
    width: int
    height: int
    byte_size: int


class EpisodeOut(BaseModel):
    id: uuid.UUID
    external_id: str | None
    #: Present on every episode, because the cross-show list would otherwise need one
    #: extra request per row just to label it.
    show_id: uuid.UUID
    show_slug: str
    show_title: str
    season_number: int
    episode_number: int
    title: str
    duration_seconds: int | None
    language: str
    content_group: str
    status: str
    artwork: list[ArtworkOut]


class ShowOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    synopsis: str
    section: str | None
    categories: list[str]
    status: str
    episode_count: int
    languages: list[str]
    artwork: list[ArtworkOut]
    updated_at: datetime


class ShowDetail(ShowOut):
    episodes: list[EpisodeOut]


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class ShowPage(BaseModel):
    items: list[ShowOut]
    page: Page


class EpisodePage(BaseModel):
    items: list[EpisodeOut]
    page: Page
