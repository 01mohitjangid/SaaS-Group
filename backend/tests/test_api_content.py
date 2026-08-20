"""CRUD and artwork upload, from an editor's point of view.

The assertions are mostly about the *messages*: the brief asks for errors a
non-technical editor can act on, so a 409 that says "conflict" would fail these tests
even though the status code is right.
"""

from __future__ import annotations

import httpx
import pytest

from app.domain.reference import ArtworkKind
from tests._api import as_editor, image_bytes, make_episode, make_show
from tests._postgres import SKIP_REASON, postgres_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not postgres_available(), reason=SKIP_REASON),
]


# --------------------------------------------------------------------------- shows


async def test_a_show_round_trips(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client)
    body = (await client.get(f"/admin/shows/{show_id}", headers=as_editor())).json()
    assert body["slug"] == "motis-many-lives"
    assert sorted(a["kind"] for a in body["artwork"]) == ["banner", "poster"]
    assert body["artwork"][0]["url"].startswith("http://testserver/media/artwork/shows/")


async def test_a_duplicate_slug_is_refused_in_plain_english(client: httpx.AsyncClient) -> None:
    await make_show(client, with_artwork=False)
    response = await client.post(
        "/admin/shows",
        json={"slug": "motis-many-lives", "title": "Another"},
        headers=as_editor(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slug_taken"
    assert "already exists" in response.json()["error"]["message"]


async def test_a_slug_with_spaces_names_the_field(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/admin/shows", json={"slug": "Moti Lives", "title": "Moti"}, headers=as_editor()
    )
    assert response.status_code == 422
    problem = response.json()["error"]["problems"][0]
    assert problem["field"] == "slug"
    assert "hyphen" in problem["message"]


async def test_a_published_show_must_have_a_section(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client, section=None)
    await make_episode(client, show_id)
    response = await client.patch(
        f"/admin/shows/{show_id}", json={"status": "published"}, headers=as_editor()
    )
    assert response.status_code == 409
    assert "section" in response.json()["error"]["message"].lower()


async def test_the_list_filters_compose(client: httpx.AsyncClient) -> None:
    await make_show(client, slug="a-show", title="Alpha", section="series", with_artwork=False)
    await make_show(client, slug="b-show", title="Beta", section="songs", with_artwork=False)

    everything = (await client.get("/admin/shows", headers=as_editor())).json()
    assert everything["page"]["total"] == 2

    filtered = (await client.get("/admin/shows?section=songs&q=bet", headers=as_editor())).json()
    assert [s["slug"] for s in filtered["items"]] == ["b-show"]

    paged = (await client.get("/admin/shows?limit=1&offset=1", headers=as_editor())).json()
    assert paged["page"] == {"total": 2, "limit": 1, "offset": 1}
    assert len(paged["items"]) == 1


# ------------------------------------------------------------------------ episodes


async def test_an_episode_cannot_be_published_without_artwork(
    client: httpx.AsyncClient,
) -> None:
    show_id = await make_show(client)
    episode_id = await make_episode(client, show_id, with_artwork=False, publish=False)
    response = await client.patch(
        f"/admin/episodes/{episode_id}", json={"status": "published"}, headers=as_editor()
    )
    assert response.status_code == 409
    assert "thumbnail" in response.json()["error"]["message"]
    assert response.json()["error"]["problems"][0]["hint"]


async def test_an_episode_cannot_be_published_without_a_duration(
    client: httpx.AsyncClient,
) -> None:
    show_id = await make_show(client)
    episode_id = await make_episode(client, show_id, duration=None, publish=False)
    response = await client.patch(
        f"/admin/episodes/{episode_id}", json={"status": "published"}, headers=as_editor()
    )
    assert response.status_code == 409
    assert "run time" in response.json()["error"]["message"]


async def test_two_versions_of_one_episode_in_the_same_language_are_refused(
    client: httpx.AsyncClient,
) -> None:
    """The `(content_group, language)` rule, as an editor experiences it."""
    show_id = await make_show(client)
    await make_episode(client, show_id, content_group="cg-1", language="en")

    response = await client.post(
        f"/admin/shows/{show_id}/episodes",
        json={
            "season_number": 1,
            "episode_number": 9,
            "title": "Duplicate",
            "duration_seconds": 100,
            "language": "en",
            "content_group": "cg-1",
        },
        headers=as_editor(),
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate_language_variant"
    assert "already a “en” version" in error["message"]


async def test_the_same_episode_in_two_languages_is_fine(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client)
    await make_episode(client, show_id, content_group="cg-1", language="en")
    await make_episode(client, show_id, content_group="cg-1", language="hi", title="Hindi")
    body = (await client.get(f"/admin/shows/{show_id}", headers=as_editor())).json()
    assert sorted(body["languages"]) == ["en", "hi"]


async def test_two_english_episodes_cannot_share_a_number(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client)
    await make_episode(client, show_id, number=4, content_group="cg-4")
    response = await client.post(
        f"/admin/shows/{show_id}/episodes",
        json={
            "season_number": 1,
            "episode_number": 4,
            "title": "Clash",
            "duration_seconds": 100,
            "language": "en",
            "content_group": "cg-other",
        },
        headers=as_editor(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_episode_number"


async def test_deleting_a_show_takes_its_episodes_with_it(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client)
    await make_episode(client, show_id)
    assert (await client.delete(f"/admin/shows/{show_id}", headers=as_editor())).status_code == 204
    assert (await client.get(f"/admin/shows/{show_id}", headers=as_editor())).status_code == 404


# ------------------------------------------------------------------------- artwork


async def test_the_specs_endpoint_tells_the_cms_what_to_show(
    client: httpx.AsyncClient,
) -> None:
    specs = (await client.get("/admin/artwork/specs", headers=as_editor())).json()
    assert specs["poster"] == {
        "aspect": "2:3",
        "target": "600×900",
        "min_width": 600,
        "min_height": 900,
        "max_kb": 200,
        "used_for": "shows",
    }
    assert specs["thumbnail"]["used_for"] == "episodes"


async def test_artwork_at_the_right_size_is_accepted(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client, with_artwork=False)
    response = await client.post(
        "/admin/artwork",
        data={"kind": "poster", "show_id": show_id},
        files={"file": ("p.jpg", image_bytes(ArtworkKind.POSTER), "image/jpeg")},
        headers=as_editor(),
    )
    assert response.status_code == 201
    assert (response.json()["width"], response.json()["height"]) == (600, 900)


async def test_the_wrong_shape_is_rejected_with_the_numbers_in_the_message(
    client: httpx.AsyncClient,
) -> None:
    show_id = await make_show(client, with_artwork=False)
    response = await client.post(
        "/admin/artwork",
        data={"kind": "poster", "show_id": show_id},
        files={
            "file": ("p.jpg", image_bytes(ArtworkKind.POSTER, width=900, height=900), "image/jpeg")
        },
        headers=as_editor(),
    )
    assert response.status_code == 422
    problem = response.json()["error"]["problems"][0]
    assert problem["field"] == "poster"
    assert "2:3" in problem["message"] and "900×900" in problem["message"]
    assert problem["hint"]


async def test_an_image_that_is_too_small_is_rejected(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client, with_artwork=False)
    response = await client.post(
        "/admin/artwork",
        data={"kind": "poster", "show_id": show_id},
        files={
            "file": ("p.jpg", image_bytes(ArtworkKind.POSTER, width=200, height=300), "image/jpeg")
        },
        headers=as_editor(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["problems"][0]["code"] == "artwork.too_small"


async def test_a_file_over_the_ceiling_is_rejected(client: httpx.AsyncClient) -> None:
    """The 200 KB limit is enforced on the bytes, not on a declared size."""
    show_id = await make_show(client, with_artwork=False)
    fat = image_bytes(ArtworkKind.POSTER, quality=100, noisy=True)
    assert len(fat) > 200 * 1024
    response = await client.post(
        "/admin/artwork",
        data={"kind": "poster", "show_id": show_id},
        files={"file": ("p.jpg", fat, "image/jpeg")},
        headers=as_editor(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["problems"][0]["code"] == "artwork.too_large"
    assert "KB" in response.json()["error"]["problems"][0]["message"]


async def test_a_file_that_is_not_an_image_is_rejected(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client, with_artwork=False)
    response = await client.post(
        "/admin/artwork",
        data={"kind": "poster", "show_id": show_id},
        files={"file": ("p.jpg", b"this is not a jpeg at all", "image/jpeg")},
        headers=as_editor(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["problems"][0]["code"] == "artwork.unreadable"


async def test_a_thumbnail_cannot_be_attached_to_a_show(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client, with_artwork=False)
    response = await client.post(
        "/admin/artwork",
        data={"kind": "thumbnail", "show_id": show_id},
        files={"file": ("t.jpg", image_bytes(ArtworkKind.THUMBNAIL), "image/jpeg")},
        headers=as_editor(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "artwork_wrong_surface"


async def test_replacing_a_poster_keeps_one_record_and_one_file(
    client: httpx.AsyncClient, api_settings: object
) -> None:
    from pathlib import Path

    from app.config import Settings

    settings: Settings = api_settings  # type: ignore[assignment]
    show_id = await make_show(client, with_artwork=False)
    for _ in range(2):
        response = await client.post(
            "/admin/artwork",
            data={"kind": "poster", "show_id": show_id},
            files={"file": ("p.jpg", image_bytes(ArtworkKind.POSTER), "image/jpeg")},
            headers=as_editor(),
        )
        assert response.status_code == 201

    listed = (await client.get(f"/admin/artwork/shows/{show_id}", headers=as_editor())).json()
    assert len(listed) == 1
    posters = list(Path(settings.storage_local_root).rglob("poster.*"))
    assert len(posters) == 1


async def test_editing_an_episode_into_a_clash_returns_a_readable_409_not_a_500(
    client: httpx.AsyncClient,
) -> None:
    """A rollback expires the ORM row; reading it afterwards used to crash the handler."""
    show_id = await make_show(client)
    await make_episode(client, show_id, number=1, content_group="cg-1", language="en")
    second = await make_episode(client, show_id, number=2, content_group="cg-2", language="en")

    response = await client.patch(
        f"/admin/episodes/{second}", json={"content_group": "cg-1"}, headers=as_editor()
    )
    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "duplicate_language_variant"


async def test_editing_an_episode_onto_a_taken_number_is_also_a_409(
    client: httpx.AsyncClient,
) -> None:
    show_id = await make_show(client)
    await make_episode(client, show_id, number=1, content_group="cg-1")
    second = await make_episode(client, show_id, number=2, content_group="cg-2")

    response = await client.patch(
        f"/admin/episodes/{second}", json={"episode_number": 1}, headers=as_editor()
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_episode_number"


async def test_deleting_a_show_removes_its_images_from_storage(
    client: httpx.AsyncClient, api_settings: object
) -> None:
    """Otherwise deleted artwork stays publicly served from the bucket forever."""
    from pathlib import Path

    from app.config import Settings

    settings: Settings = api_settings  # type: ignore[assignment]
    show_id = await make_show(client)
    await make_episode(client, show_id)

    root = Path(settings.storage_local_root)
    assert len(list(root.rglob("*.jpg"))) == 3  # poster, banner, thumbnail

    assert (await client.delete(f"/admin/shows/{show_id}", headers=as_editor())).status_code == 204
    assert list(root.rglob("*.jpg")) == []


async def test_deleting_an_episode_removes_only_its_own_image(
    client: httpx.AsyncClient, api_settings: object
) -> None:
    from pathlib import Path

    from app.config import Settings

    settings: Settings = api_settings  # type: ignore[assignment]
    show_id = await make_show(client)
    episode_id = await make_episode(client, show_id)
    root = Path(settings.storage_local_root)

    assert (
        await client.delete(f"/admin/episodes/{episode_id}", headers=as_editor())
    ).status_code == 204
    remaining = sorted(p.name for p in root.rglob("*.jpg"))
    assert remaining == ["banner.jpg", "poster.jpg"]


async def test_deleting_one_image_leaves_the_others(
    client: httpx.AsyncClient, api_settings: object
) -> None:
    from pathlib import Path

    from app.config import Settings

    settings: Settings = api_settings  # type: ignore[assignment]
    show_id = await make_show(client)
    listed = (await client.get(f"/admin/artwork/shows/{show_id}", headers=as_editor())).json()
    poster = next(a for a in listed if a["kind"] == "poster")

    assert (
        await client.delete(f"/admin/artwork/{poster['id']}", headers=as_editor())
    ).status_code == 204
    remaining = sorted(p.name for p in Path(settings.storage_local_root).rglob("*.jpg"))
    assert remaining == ["banner.jpg"]


async def test_uploading_to_neither_owner_explains_what_is_wrong(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/admin/artwork",
        data={"kind": "poster"},
        files={"file": ("p.jpg", image_bytes(ArtworkKind.POSTER), "image/jpeg")},
        headers=as_editor(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "artwork_needs_one_owner"


# ------------------------------------------------------------------- episode list


async def test_the_episode_list_searches_and_filters(client: httpx.AsyncClient) -> None:
    """Part B.1 wants an episode list; it also gives ix_episodes_title_trgm a reason to exist."""
    moti = await make_show(client, slug="motis-many-lives", title="Moti", section="featured")
    await make_episode(client, moti, number=1, content_group="cg-1", title="The Lost Kite")
    await make_episode(
        client, moti, number=1, content_group="cg-1", language="hi", title="Hindi Kite"
    )
    songs = await make_show(client, slug="peblo-songs", title="Songs", section="songs")
    await make_episode(
        client, songs, number=1, content_group="cg-s", title="Rain on the Roof", publish=False
    )

    everything = (await client.get("/admin/episodes", headers=as_editor())).json()
    assert everything["page"]["total"] == 3

    by_title = (await client.get("/admin/episodes?q=kite", headers=as_editor())).json()
    assert sorted(e["title"] for e in by_title["items"]) == ["Hindi Kite", "The Lost Kite"]

    assert (await client.get("/admin/episodes?show_slug=peblo-songs", headers=as_editor())).json()[
        "page"
    ]["total"] == 1
    assert (await client.get("/admin/episodes?language=hi", headers=as_editor())).json()["page"][
        "total"
    ] == 1
    assert (await client.get("/admin/episodes?status=draft", headers=as_editor())).json()["page"][
        "total"
    ] == 1

    composed = (await client.get("/admin/episodes?q=kite&language=hi", headers=as_editor())).json()
    assert [e["title"] for e in composed["items"]] == ["Hindi Kite"]

    paged = (await client.get("/admin/episodes?limit=1&offset=2", headers=as_editor())).json()
    assert paged["page"] == {"total": 3, "limit": 1, "offset": 2}
    assert len(paged["items"]) == 1


async def test_the_episode_list_carries_what_the_cms_needs(client: httpx.AsyncClient) -> None:
    show_id = await make_show(client)
    await make_episode(client, show_id)
    (episode,) = (await client.get("/admin/episodes", headers=as_editor())).json()["items"]
    assert episode["season_number"] == 1
    assert episode["duration_seconds"] == 510
    assert [a["kind"] for a in episode["artwork"]] == ["thumbnail"]
    assert episode["artwork"][0]["url"].startswith("http://testserver/media/artwork/episodes/")


async def test_the_admin_list_does_not_treat_wildcards_as_wildcards(
    client: httpx.AsyncClient,
) -> None:
    """`q=%` used to return every show in the CMS."""
    await make_show(client, slug="a-show", title="Alpha", with_artwork=False)
    await make_show(client, slug="b-show", title="Beta", with_artwork=False)
    for wildcard in ("%", "_", "%%"):
        body = (await client.get(f"/admin/shows?q={wildcard}", headers=as_editor())).json()
        assert body["page"]["total"] == 0, wildcard
    assert (await client.get("/admin/shows?q=alph", headers=as_editor())).json()["page"][
        "total"
    ] == 1


async def test_the_episode_list_says_which_show_each_row_belongs_to(
    client: httpx.AsyncClient,
) -> None:
    """A cross-show list that cannot label its rows costs the CMS a request per row."""
    moti = await make_show(client, slug="motis-many-lives", title="Moti's Many Lives")
    await make_episode(client, moti, content_group="cg-1")
    (episode,) = (await client.get("/admin/episodes", headers=as_editor())).json()["items"]
    assert episode["show_slug"] == "motis-many-lives"
    assert episode["show_title"] == "Moti's Many Lives"
    assert episode["show_id"] == moti


async def test_the_reference_endpoint_is_the_cms_source_of_truth(
    client: httpx.AsyncClient,
) -> None:
    """Otherwise the CMS keeps its own copy and drifts from what the API validates."""
    reference = (await client.get("/admin/reference", headers=as_editor())).json()
    assert reference["sections"] == ["featured", "series", "minisodes", "songs"]
    assert reference["languages"] == ["en", "hi"]
    assert len(reference["categories"]) == 15
    assert reference["statuses"] == ["draft", "published"]
    assert reference["artwork"]["poster"]["target"] == "600×900"

    # A section it lists is accepted; one it does not is refused.
    ok = await client.post(
        "/admin/shows",
        json={"slug": "ok-show", "title": "Ok", "section": reference["sections"][0]},
        headers=as_editor(),
    )
    assert ok.status_code == 201
