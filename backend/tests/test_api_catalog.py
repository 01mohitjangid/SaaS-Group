"""What the viewer sees: the published catalogue, search, and nothing else.

Two rules from the brief get their own tests here because they are easy to get subtly
wrong: language variants must collapse into one entry, and Season 0 must not appear as
a season.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests._api import as_admin, as_editor, make_episode, make_show, publish_show
from tests._postgres import SKIP_REASON, postgres_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not postgres_available(), reason=SKIP_REASON),
]


async def _catalogue(client: httpx.AsyncClient) -> dict[str, Any]:
    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 201
    response = await client.get("/catalog")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def _moti(client: httpx.AsyncClient) -> str:
    show_id = await make_show(client)
    await make_episode(client, show_id, content_group="cg-1", language="en")
    await publish_show(client, show_id)
    return show_id


# ------------------------------------------------------------------- before publish


async def test_the_catalogue_is_honest_before_anything_is_published(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/catalog")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "catalog_not_published"


# ------------------------------------------------------------------------- shaping


async def test_language_variants_collapse_into_one_entry(client: httpx.AsyncClient) -> None:
    show_id = await _moti(client)
    await make_episode(client, show_id, content_group="cg-1", language="hi", title="Hindi Title")

    show = (await _catalogue(client))["sections"][0]["shows"][0]
    (episode,) = show["seasons"][0]["episodes"]
    assert episode["languages"] == ["en", "hi"]
    assert episode["title"] == "The Lost Kite"  # English is the master
    assert show["languages"] == ["en", "hi"]


async def test_season_zero_is_trailers_not_a_season(client: httpx.AsyncClient) -> None:
    show_id = await _moti(client)
    await make_episode(
        client, show_id, season=0, number=1, title="Trailer", content_group="cg-trailer"
    )

    show = (await _catalogue(client))["sections"][0]["shows"][0]
    assert [s["season_number"] for s in show["seasons"]] == [1]
    assert [t["title"] for t in show["trailers"]] == ["Trailer"]


async def test_drafts_never_reach_the_viewer(client: httpx.AsyncClient) -> None:
    show_id = await _moti(client)
    await make_episode(
        client, show_id, number=2, content_group="cg-2", title="Secret", publish=False
    )
    await make_show(client, slug="hidden", title="Hidden", with_artwork=False)

    catalogue = await _catalogue(client)
    titles = [
        e["title"]
        for section in catalogue["sections"]
        for show in section["shows"]
        for season in show["seasons"]
        for e in season["episodes"]
    ]
    assert "Secret" not in titles
    assert "hidden" not in [
        s["slug"] for section in catalogue["sections"] for s in section["shows"]
    ]


async def test_each_surface_gets_the_right_artwork(client: httpx.AsyncClient) -> None:
    await _moti(client)
    show = (await _catalogue(client))["sections"][0]["shows"][0]
    assert set(show["artwork"]) == {"poster", "banner"}
    assert set(show["seasons"][0]["episodes"][0]["artwork"]) == {"thumbnail"}


async def test_sections_come_back_in_the_content_teams_order(
    client: httpx.AsyncClient,
) -> None:
    for slug, section in (("songs-show", "songs"), ("featured-show", "featured")):
        show_id = await make_show(client, slug=slug, title=slug, section=section)
        await make_episode(client, show_id, content_group=f"cg-{slug}")
        await publish_show(client, show_id)

    catalogue = await _catalogue(client)
    assert [s["key"] for s in catalogue["sections"]] == ["featured", "songs"]


async def test_a_show_detail_route_serves_from_the_published_file(
    client: httpx.AsyncClient,
) -> None:
    await _moti(client)
    await _catalogue(client)
    response = await client.get("/catalog/shows/motis-many-lives")
    assert response.status_code == 200
    assert response.json()["section"] == "featured"
    assert (await client.get("/catalog/shows/nope")).status_code == 404


# -------------------------------------------------------------------------- search


async def _searchable(client: httpx.AsyncClient) -> None:
    moti = await make_show(
        client,
        slug="motis-many-lives",
        title="Moti's Many Lives",
        section="featured",
        categories=["adventure", "india"],
    )
    await make_episode(client, moti, content_group="cg-moti", title="The Lost Kite")
    await make_episode(client, moti, content_group="cg-moti", language="hi", title="Hindi Kite")
    await publish_show(client, moti)

    songs = await make_show(
        client,
        slug="peblo-songs",
        title="Peblo Songs",
        section="songs",
        categories=["music", "singalong"],
    )
    await make_episode(client, songs, content_group="cg-song", title="Rain on the Roof")
    await publish_show(client, songs)
    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 201


async def test_search_matches_a_show_title(client: httpx.AsyncClient) -> None:
    await _searchable(client)
    body = (await client.get("/catalog/search?q=moti")).json()
    assert [r["slug"] for r in body["results"]] == ["motis-many-lives"]


async def test_search_matches_an_episode_title(client: httpx.AsyncClient) -> None:
    """`q` has to reach episode titles, not just show titles."""
    await _searchable(client)
    body = (await client.get("/catalog/search?q=rain on the roof")).json()
    assert [r["slug"] for r in body["results"]] == ["peblo-songs"]


async def test_search_matches_a_category(client: httpx.AsyncClient) -> None:
    await _searchable(client)
    body = (await client.get("/catalog/search?q=singalong")).json()
    assert [r["slug"] for r in body["results"]] == ["peblo-songs"]


async def test_every_filter_composes(client: httpx.AsyncClient) -> None:
    await _searchable(client)

    assert len((await client.get("/catalog/search")).json()["results"]) == 2
    assert len((await client.get("/catalog/search?section=songs")).json()["results"]) == 1
    assert len((await client.get("/catalog/search?category=india")).json()["results"]) == 1
    assert len((await client.get("/catalog/search?language=hi")).json()["results"]) == 1

    # Composed: a Hindi episode in the featured section matching "kite".
    both = (await client.get("/catalog/search?q=kite&language=hi&section=featured")).json()
    assert [r["slug"] for r in both["results"]] == ["motis-many-lives"]

    # Composed contradiction returns an empty result, not everything.
    none = (await client.get("/catalog/search?q=kite&section=songs")).json()
    assert none["results"] == []
    assert none["total"] == 0


async def test_search_reports_which_catalogue_version_it_lines_up_with(
    client: httpx.AsyncClient,
) -> None:
    await _searchable(client)
    live = (await client.get("/catalog")).json()
    body = (await client.get("/catalog/search?q=moti")).json()
    assert body["catalog_version"] == live["version"]


async def test_search_pages(client: httpx.AsyncClient) -> None:
    await _searchable(client)
    page = (await client.get("/catalog/search?limit=1&offset=1")).json()
    assert page["total"] == 2
    assert len(page["results"]) == 1


async def test_search_never_returns_a_draft(client: httpx.AsyncClient) -> None:
    await _searchable(client)
    await make_show(client, slug="secret-show", title="Secret Moti", with_artwork=False)
    body = (await client.get("/catalog/search?q=moti")).json()
    assert "secret-show" not in [r["slug"] for r in body["results"]]


async def test_search_needs_no_credentials_and_leaks_no_admin_fields(
    client: httpx.AsyncClient,
) -> None:
    await _searchable(client)
    body = (await client.get("/catalog/search?q=moti")).json()
    assert body["results"]
    for result in body["results"]:
        assert set(result) == {
            "section",
            "slug",
            "title",
            "synopsis",
            "categories",
            "languages",
            "artwork",
        }


async def test_a_search_hit_always_has_a_working_detail_page(
    client: httpx.AsyncClient,
) -> None:
    """Search indexes the database but serves the published file, so the two agree.

    Before this, a show published in the CMS but not yet in a publish run appeared in
    search with a detail link that 404'd.
    """
    await _searchable(client)
    late = await make_show(client, slug="late-show", title="Late Moti", section="series")
    await make_episode(client, late, content_group="cg-late", title="Late Kite")
    await publish_show(client, late)  # published in the CMS, not yet in the catalogue

    body = (await client.get("/catalog/search?q=moti")).json()
    slugs = [r["slug"] for r in body["results"]]
    assert "late-show" not in slugs

    for slug in slugs:
        assert (await client.get(f"/catalog/shows/{slug}")).status_code == 200

    # After publishing, it appears — and its detail page works.
    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 201
    after = (await client.get("/catalog/search?q=moti")).json()
    assert "late-show" in [r["slug"] for r in after["results"]]
    assert (await client.get("/catalog/shows/late-show")).status_code == 200


async def test_search_before_the_first_publish_is_empty_not_an_error(
    client: httpx.AsyncClient,
) -> None:
    await make_show(client, with_artwork=False)
    body = (await client.get("/catalog/search?q=moti")).json()
    assert body["results"] == []
    assert body["total"] == 0
    assert body["catalog_version"] is None


async def test_like_wildcards_in_the_query_are_not_wildcards(
    client: httpx.AsyncClient,
) -> None:
    """`q=%` used to match the entire catalogue."""
    await _searchable(client)
    for wildcard in ("%", "_", "%%"):
        body = (await client.get(f"/catalog/search?q={wildcard}")).json()
        assert body["results"] == [], wildcard


async def test_search_results_are_read_from_the_published_document(
    client: httpx.AsyncClient,
) -> None:
    """An edit that has not been published must not change what search shows."""
    await _searchable(client)
    show_id = (await client.get("/admin/shows?q=motis", headers=as_editor())).json()["items"][0][
        "id"
    ]
    await client.patch(
        f"/admin/shows/{show_id}", json={"title": "Renamed Before Publish"}, headers=as_editor()
    )

    body = (await client.get("/catalog/search?q=moti")).json()
    assert [r["title"] for r in body["results"]] == ["Moti's Many Lives"]


async def test_the_catalogue_is_cacheable_because_a_run_never_changes(
    client: httpx.AsyncClient,
) -> None:
    await _moti(client)
    first = await _catalogue(client)

    response = await client.get("/catalog")
    etag = response.headers["ETag"]
    assert response.headers["Cache-Control"] == "public, max-age=60"

    unchanged = await client.get("/catalog", headers={"If-None-Match": etag})
    assert unchanged.status_code == 304
    assert unchanged.content == b""

    # A new publish changes the version, so the old ETag stops matching.
    await make_episode(
        client,
        (await client.get("/admin/shows", headers=as_editor())).json()["items"][0]["id"],
        number=2,
        content_group="cg-2",
        title="Second",
    )
    second = await _catalogue(client)
    assert second["version"] != first["version"]
    assert (await client.get("/catalog", headers={"If-None-Match": etag})).status_code == 200
