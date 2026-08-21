"""The artwork upload endpoint.

Three labelled slots, one endpoint: the ``kind`` says which surface the file is for,
and the specs for that surface come from ``reference.json``. Every rejection is a
sentence an editor can act on, with the numbers in it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from sqlalchemy import select

from app.api.deps import EditorUser, ReferenceDep, SessionDep, StorageDep
from app.db.models import Artwork, Episode, Show
from app.domain.reference import ArtworkKind
from app.errors import ApiError, NotFound
from app.schemas.content import ArtworkOut
from app.services.artwork import MAX_UPLOAD_BYTES, delete_artwork, store_artwork

router = APIRouter(prefix="/admin/artwork", tags=["artwork"])

reference_router = APIRouter(prefix="/admin", tags=["content"])


@reference_router.get("/me", summary="Who the current token belongs to, and what it may do")
async def whoami(user: EditorUser) -> dict[str, object]:
    """The CMS needs this to disable publish *with a reason* rather than by guessing.

    Without it the only way to discover a role is to attempt the action and read the
    403 — which means showing an editor a button that always fails.
    """
    return {
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "can_publish": user.role == "admin",
    }


@reference_router.get(
    "/reference",
    summary="The allowed sections, categories and languages, for the CMS's pickers",
)
async def content_reference(reference: ReferenceDep, _: EditorUser) -> dict[str, object]:
    """One source of truth for the vocabularies.

    Without this the CMS ends up with its own copy of `reference.json`, which drifts
    from the copy the rules engine validates against — and the editor finds out by
    picking a category the API then rejects.
    """
    return {
        "sections": list(reference.sections),
        "categories": list(reference.categories),
        "languages": list(reference.languages),
        "statuses": ["draft", "published"],
        "artwork": {
            kind.value: {
                "aspect": spec.aspect_label,
                "target": spec.target_label,
                "min_width": spec.target_width,
                "min_height": spec.target_height,
                "max_kb": spec.max_bytes // 1024,
                "used_for": "shows" if kind is not ArtworkKind.THUMBNAIL else "episodes",
            }
            for kind, spec in reference.artwork.items()
        },
    }


def _out(record: Artwork, url: str) -> ArtworkOut:
    return ArtworkOut(
        id=record.id,
        kind=record.kind,
        url=url,
        width=record.width,
        height=record.height,
        byte_size=record.byte_size,
    )


@router.get("/specs", summary="What each slot requires, for the CMS to display")
async def artwork_specs(reference: ReferenceDep, _: EditorUser) -> dict[str, dict[str, object]]:
    return {
        kind.value: {
            "aspect": spec.aspect_label,
            "target": spec.target_label,
            "min_width": spec.target_width,
            "min_height": spec.target_height,
            "max_kb": spec.max_bytes // 1024,
            "used_for": "shows" if kind is not ArtworkKind.THUMBNAIL else "episodes",
        }
        for kind, spec in reference.artwork.items()
    }


@router.post(
    "",
    response_model=ArtworkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload artwork for a show (poster/banner) or an episode (thumbnail)",
)
async def upload_artwork(
    session: SessionDep,
    storage: StorageDep,
    reference: ReferenceDep,
    _: EditorUser,
    kind: Annotated[ArtworkKind, Form(description="poster, banner or thumbnail")],
    file: Annotated[UploadFile, File()],
    show_id: Annotated[uuid.UUID | None, Form()] = None,
    episode_id: Annotated[uuid.UUID | None, Form()] = None,
) -> ArtworkOut:
    if (show_id is None) == (episode_id is None):
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="artwork_needs_one_owner",
            message="Say which show or which episode this image belongs to — exactly one.",
            problems=[
                {
                    "field": "show_id",
                    "message": "Provide either show_id or episode_id, not both and not neither.",
                    "hint": "Posters and banners go on a show; thumbnails go on an episode.",
                }
            ],
        )

    show = episode = None
    if show_id is not None:
        show = await session.get(Show, show_id)
        if show is None:
            raise NotFound("show")
    else:
        episode = await session.get(Episode, episode_id)
        if episode is None:
            raise NotFound("episode")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    record = await store_artwork(
        session, storage, reference, kind=kind, data=data, show=show, episode=episode
    )
    await session.commit()
    return _out(record, storage.url_for(record.storage_key))


@router.get("/{owner}/{owner_id}", response_model=list[ArtworkOut], summary="What is uploaded")
async def list_artwork(
    owner: str, owner_id: uuid.UUID, session: SessionDep, storage: StorageDep, _: EditorUser
) -> list[ArtworkOut]:
    if owner not in {"shows", "episodes"}:
        raise NotFound("owner")
    column = Artwork.show_id if owner == "shows" else Artwork.episode_id
    rows = (await session.execute(select(Artwork).where(column == owner_id))).scalars().all()
    return [_out(a, storage.url_for(a.storage_key)) for a in sorted(rows, key=lambda a: a.kind)]


@router.delete("/{artwork_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an image")
async def remove_artwork(
    artwork_id: uuid.UUID, session: SessionDep, storage: StorageDep, _: EditorUser
) -> None:
    key = await delete_artwork(session, storage, artwork_id)
    await session.commit()
    await storage.delete(key)
