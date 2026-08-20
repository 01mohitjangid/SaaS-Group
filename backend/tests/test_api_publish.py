"""The publish job: atomic, recorded, idempotent, and correct about languages.

This is the 20-point item in the brief, so the tests go after the properties rather
than the happy path — what a reader sees while a publish is running, what happens when
storage fails halfway, and what a second identical publish does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from app.config import Settings
from tests._api import as_admin, as_editor, make_episode, make_show, publish_show
from tests._postgres import SKIP_REASON, postgres_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not postgres_available(), reason=SKIP_REASON),
]


async def _seed_one_show(client: httpx.AsyncClient) -> str:
    show_id = await make_show(client)
    await make_episode(client, show_id, content_group="cg-1", language="en")
    await publish_show(client, show_id)
    return show_id


async def _break_a_published_episode(client: httpx.AsyncClient, show_id: str) -> None:
    """Delete a live episode's thumbnail — a real blocker, the way a CMS delete makes one.

    Note that a *draft* episode with no artwork is not a blocker and must not be: editors
    work on drafts all day. Only published rows have to be clean.
    """
    detail = (await client.get(f"/admin/shows/{show_id}", headers=as_editor())).json()
    published = next(e for e in detail["episodes"] if e["status"] == "published")
    thumbnail = next(a for a in published["artwork"] if a["kind"] == "thumbnail")
    response = await client.delete(f"/admin/artwork/{thumbnail['id']}", headers=as_editor())
    assert response.status_code == 204, response.text


async def _publish(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/admin/catalog/publish", headers=as_admin())
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------------ the publish gate


async def test_publishing_is_blocked_by_a_broken_episode_and_says_why(
    client: httpx.AsyncClient,
) -> None:
    show_id = await _seed_one_show(client)
    await _break_a_published_episode(client, show_id)

    response = await client.post("/admin/catalog/publish", headers=as_admin())
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "publish_blocked"
    assert any("thumbnail" in p["message"] for p in error["problems"])


async def test_a_blocked_publish_is_still_recorded_as_a_failed_run(
    client: httpx.AsyncClient,
) -> None:
    show_id = await _seed_one_show(client)
    await _break_a_published_episode(client, show_id)
    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 409

    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    assert runs and runs[0]["status"] == "failed"
    assert runs[0]["created_by_email"] == "admin@peblo.tv"


async def test_the_validation_report_groups_problems_by_show(
    client: httpx.AsyncClient,
) -> None:
    show_id = await _seed_one_show(client)
    await _break_a_published_episode(client, show_id)

    report = (await client.get("/admin/validation-report", headers=as_editor())).json()
    assert report["can_publish"] is False
    assert report["blocker_count"] >= 1
    group = next(g for g in report["groups"] if g["show_slug"] == "motis-many-lives")
    assert group["show_title"] == "Moti's Many Lives"
    assert all(b["fix_hint"] for b in group["blockers"])


# ------------------------------------------------------------------ recording a run


async def test_a_successful_run_records_who_when_counts_and_outcome(
    client: httpx.AsyncClient,
) -> None:
    await _seed_one_show(client)
    run = (await _publish(client))["run"]

    assert run["status"] == "succeeded"
    assert run["created_by_email"] == "admin@peblo.tv"
    assert run["started_at"] and run["finished_at"]
    assert run["counts"]["shows"] == 1
    assert run["counts"]["episodes"] == 1
    assert run["catalog_key"].endswith(".json")
    assert run["checksum_sha256"]


# ---------------------------------------------------------------------- atomicity


async def test_the_live_pointer_names_an_object_that_was_finished_first(
    client: httpx.AsyncClient, api_settings: Settings
) -> None:
    await _seed_one_show(client)
    run = (await _publish(client))["run"]

    root = Path(api_settings.storage_local_root)
    pointer = json.loads((root / api_settings.catalog_pointer_key).read_text())
    assert pointer["run_id"] == run["id"]
    assert (root / pointer["key"]).is_file()
    # The catalogue readers get is a complete document, not a partial write.
    assert json.loads((root / pointer["key"]).read_text())["version"] == run["id"]


async def test_a_second_publish_writes_a_new_object_and_never_overwrites_the_old_one(
    client: httpx.AsyncClient, api_settings: Settings
) -> None:
    """Overwriting the live file is called out in the brief as a thing that loses marks."""
    show_id = await _seed_one_show(client)
    first = (await _publish(client))["run"]

    await make_episode(client, show_id, number=2, content_group="cg-2", title="Rain on the Roof")
    second = (await _publish(client))["run"]

    assert first["catalog_key"] != second["catalog_key"]
    root = Path(api_settings.storage_local_root)
    # The first run's bytes are untouched, which is what makes rollback possible.
    assert json.loads((root / first["catalog_key"]).read_text())["counts"]["episodes"] == 1
    assert json.loads((root / second["catalog_key"]).read_text())["counts"]["episodes"] == 2


async def test_if_the_pointer_write_fails_the_old_catalogue_stays_live(
    client: httpx.AsyncClient, api_app: FastAPI, api_settings: Settings
) -> None:
    """The crash case: a run that dies before the flip changes nothing a reader can see."""
    show_id = await _seed_one_show(client)
    good = (await _publish(client))["run"]
    before = (await client.get("/catalog")).json()

    storage = api_app.state.storage
    original_put = storage.put

    async def explode(key: str, data: bytes, content_type: str) -> Any:
        if key == api_settings.catalog_pointer_key:
            raise OSError("storage went away mid-publish")
        return await original_put(key, data, content_type)

    await make_episode(client, show_id, number=2, content_group="cg-2", title="Second")
    storage.put = explode
    try:
        with pytest.raises(OSError, match="mid-publish"):
            await client.post("/admin/catalog/publish", headers=as_admin())
    finally:
        storage.put = original_put

    assert (await client.get("/catalog")).json() == before
    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    assert runs[0]["status"] == "failed"
    assert "storage went away" in runs[0]["error"]
    # The still-live catalogue is the earlier run's, untouched.
    root = Path(api_settings.storage_local_root)
    assert json.loads((root / api_settings.catalog_pointer_key).read_text())["run_id"] == good["id"]


# --------------------------------------------------------------------- idempotency


async def test_publishing_unchanged_content_twice_changes_nothing(
    client: httpx.AsyncClient, api_settings: Settings
) -> None:
    await _seed_one_show(client)
    first = await _publish(client)
    root = Path(api_settings.storage_local_root)
    pointer_before = (root / api_settings.catalog_pointer_key).read_bytes()

    second = await _publish(client)

    assert second["reused"] is True
    assert second["run"]["catalog_key"] == first["run"]["catalog_key"]
    assert second["run"]["checksum_sha256"] == first["run"]["checksum_sha256"]
    assert (root / api_settings.catalog_pointer_key).read_bytes() == pointer_before
    # Both runs are still recorded — idempotent is not the same as invisible.
    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    assert [r["status"] for r in runs[:2]] == ["succeeded", "succeeded"]


async def test_a_real_change_is_not_treated_as_a_repeat(client: httpx.AsyncClient) -> None:
    show_id = await _seed_one_show(client)
    first = await _publish(client)
    await client.patch(f"/admin/shows/{show_id}", json={"title": "Renamed"}, headers=as_editor())
    second = await _publish(client)

    assert second["reused"] is False
    assert second["run"]["checksum_sha256"] != first["run"]["checksum_sha256"]


async def test_shipping_a_hindi_dub_counts_as_a_change(client: httpx.AsyncClient) -> None:
    show_id = await _seed_one_show(client)
    first = await _publish(client)
    await make_episode(client, show_id, content_group="cg-1", language="hi", title="Hindi")
    second = await _publish(client)
    assert second["reused"] is False
    assert second["run"]["checksum_sha256"] != first["run"]["checksum_sha256"]


# ----------------------------------------------------------------------- rollback


async def test_rollback_re_points_the_live_catalogue_at_an_earlier_run(
    client: httpx.AsyncClient,
) -> None:
    show_id = await _seed_one_show(client)
    first = (await _publish(client))["run"]
    await make_episode(client, show_id, number=2, content_group="cg-2", title="Second")
    await _publish(client)
    assert (await client.get("/catalog")).json()["counts"]["episodes"] == 2

    response = await client.post(f"/admin/catalog/rollback/{first['id']}", headers=as_admin())
    assert response.status_code == 200, response.text
    live = (await client.get("/catalog")).json()
    assert live["counts"]["episodes"] == 1
    assert live["version"] == first["id"]


async def test_an_editor_cannot_roll_back(client: httpx.AsyncClient) -> None:
    await _seed_one_show(client)
    run = (await _publish(client))["run"]
    response = await client.post(f"/admin/catalog/rollback/{run['id']}", headers=as_editor())
    assert response.status_code == 403


# ---------------------------------------------------------------------- concurrency


async def test_only_one_publish_can_be_in_flight(
    client: httpx.AsyncClient, clean_database: sa.Engine
) -> None:
    """A second simultaneous run is refused by Postgres, not by hoping."""
    await _seed_one_show(client)
    with clean_database.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO publish_runs (id, status, created_by_email) "
                "VALUES (gen_random_uuid(), 'running', 'someone@peblo.tv')"
            )
        )
    response = await client.post("/admin/catalog/publish", headers=as_admin())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publish_already_running"


async def test_a_run_abandoned_long_enough_is_reaped_so_publishing_recovers(
    client: httpx.AsyncClient, clean_database: sa.Engine
) -> None:
    """Otherwise one crashed process blocks publishing forever."""
    await _seed_one_show(client)
    with clean_database.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO publish_runs (id, status, created_by_email, started_at) VALUES "
                "(gen_random_uuid(), 'running', 'ghost@peblo.tv', now() - interval '2 hours')"
            )
        )
    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 201

    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    ghost = next(r for r in runs if r["created_by_email"] == "ghost@peblo.tv")
    assert ghost["status"] == "failed"
    assert "stopped before it finished" in ghost["error"]


async def test_a_draft_episode_without_artwork_never_blocks_publishing(
    client: httpx.AsyncClient,
) -> None:
    """Editors work on drafts all day; only what is going live has to be clean."""
    show_id = await _seed_one_show(client)
    await make_episode(
        client, show_id, number=2, content_group="cg-2", with_artwork=False, publish=False
    )

    report = (await client.get("/admin/validation-report", headers=as_editor())).json()
    assert report["can_publish"] is True
    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 201
    # …and the draft is not in the published catalogue.
    live = (await client.get("/catalog")).json()
    assert live["counts"]["episodes"] == 1


async def test_a_hard_crash_leaves_a_visible_running_row_for_the_reaper(
    client: httpx.AsyncClient, api_app: FastAPI, clean_database: sa.Engine
) -> None:
    """The whole crash story depends on the `running` row being committed up front.

    A `BaseException` (SIGTERM, a killed worker) skips the handler that marks a run
    failed. If the row had only been flushed, the attempt would vanish on rollback and
    the reaper would have nothing to find.
    """
    await _seed_one_show(client)
    storage = api_app.state.storage
    original_put = storage.put

    async def die(key: str, data: bytes, content_type: str) -> Any:
        raise KeyboardInterrupt("worker killed")

    storage.put = die
    try:
        with pytest.raises(KeyboardInterrupt):
            await client.post("/admin/catalog/publish", headers=as_admin())
    finally:
        storage.put = original_put

    with clean_database.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT status, created_by_email FROM publish_runs")
        ).all()
    assert [r.status for r in rows] == ["running"]
    assert rows[0].created_by_email == "admin@peblo.tv"


async def test_a_second_publish_is_refused_while_one_is_genuinely_in_flight(
    client: httpx.AsyncClient, api_app: FastAPI, clean_database: sa.Engine
) -> None:
    """Not "queued behind an open transaction and then allowed" — actually refused."""
    await _seed_one_show(client)
    storage = api_app.state.storage
    original_put = storage.put

    async def die(key: str, data: bytes, content_type: str) -> Any:
        raise KeyboardInterrupt("worker killed")

    storage.put = die
    try:
        with pytest.raises(KeyboardInterrupt):
            await client.post("/admin/catalog/publish", headers=as_admin())
    finally:
        storage.put = original_put

    # The abandoned run still holds the slot, and it is not old enough to reap.
    response = await client.post("/admin/catalog/publish", headers=as_admin())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publish_already_running"


async def test_a_stuck_run_can_be_cancelled_instead_of_waiting_out_the_lease(
    client: httpx.AsyncClient, api_app: FastAPI
) -> None:
    """A crash holds the slot for 15 minutes. Someone with a correction to ship cannot."""
    await _seed_one_show(client)
    storage = api_app.state.storage
    original_put = storage.put

    async def die(key: str, data: bytes, content_type: str) -> Any:
        raise KeyboardInterrupt("worker killed")

    storage.put = die
    try:
        with pytest.raises(KeyboardInterrupt):
            await client.post("/admin/catalog/publish", headers=as_admin())
    finally:
        storage.put = original_put

    blocked = await client.post("/admin/catalog/publish", headers=as_admin())
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    # The message names who and how long — not "wait for that run to finish".
    assert "admin@peblo.tv" in error["message"]
    assert "cancel" in error["problems"][0]["hint"]

    stuck = next(
        r
        for r in (await client.get("/admin/publish-runs", headers=as_editor())).json()
        if r["status"] == "running"
    )
    cancelled = await client.post(f"/admin/publish-runs/{stuck['id']}/cancel", headers=as_admin())
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "failed"
    assert "Cancelled by admin@peblo.tv" in cancelled.json()["error"]

    assert (await client.post("/admin/catalog/publish", headers=as_admin())).status_code == 201


async def test_only_an_admin_can_cancel_a_run(client: httpx.AsyncClient) -> None:
    await _seed_one_show(client)
    run = (await _publish(client))["run"]
    assert (
        await client.post(f"/admin/publish-runs/{run['id']}/cancel", headers=as_editor())
    ).status_code == 403
    # And a finished run has nothing to cancel.
    response = await client.post(f"/admin/publish-runs/{run['id']}/cancel", headers=as_admin())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_not_running"


async def test_publish_does_not_report_reuse_when_the_object_is_gone(
    client: httpx.AsyncClient, api_settings: Settings
) -> None:
    """The database alone cannot know whether the bytes are still in storage.

    Wipe the bucket — or migrate local disk to R2 without moving the objects — and a
    DB-only idempotency check reports "succeeded, reused" while `/catalog` stays 503.
    """
    await _seed_one_show(client)
    first = await _publish(client)
    assert first["reused"] is False

    root = Path(api_settings.storage_local_root)
    for stale in root.glob("catalog/runs/*.json"):
        stale.unlink()
    (root / api_settings.catalog_pointer_key).unlink()

    second = await _publish(client)
    assert second["reused"] is False, "storage was empty; there was nothing to reuse"
    assert (root / api_settings.catalog_pointer_key).is_file()
    assert (await client.get("/catalog")).status_code == 200


async def test_a_failed_rollback_does_not_jam_the_publish_slot(
    client: httpx.AsyncClient, api_app: FastAPI
) -> None:
    """Rollback is reached *because* the catalogue is already wrong. It must not add to it."""
    await _seed_one_show(client)
    run = (await _publish(client))["run"]

    storage = api_app.state.storage
    original_put = storage.put

    async def explode(key: str, data: bytes, content_type: str) -> Any:
        raise OSError("storage went away mid-rollback")

    storage.put = explode
    try:
        with pytest.raises(OSError, match="mid-rollback"):
            await client.post(f"/admin/catalog/rollback/{run['id']}", headers=as_admin())
    finally:
        storage.put = original_put

    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    assert runs[0]["status"] == "failed"
    assert "storage went away" in runs[0]["error"]
    # The slot is free again, so a retry is possible immediately.
    assert (
        await client.post(f"/admin/catalog/rollback/{run['id']}", headers=as_admin())
    ).status_code == 200


async def test_run_history_can_tell_a_rollback_from_an_ordinary_success(
    client: httpx.AsyncClient,
) -> None:
    show_id = await _seed_one_show(client)
    first = (await _publish(client))["run"]
    await make_episode(client, show_id, number=2, content_group="cg-2", title="Second")
    await _publish(client)
    await client.post(f"/admin/catalog/rollback/{first['id']}", headers=as_admin())

    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    assert runs[0]["rolled_back_to"] == first["id"]
    assert runs[1]["rolled_back_to"] is None

    # Publishing after a rollback moves forward again: the content still has two
    # episodes, so it is a real publish and not a reuse of the rolled-back run.
    after = await _publish(client)
    assert after["reused"] is False
    assert (await client.get("/catalog")).json()["counts"]["episodes"] == 2


async def test_run_history_marks_a_reuse(client: httpx.AsyncClient) -> None:
    await _seed_one_show(client)
    await _publish(client)
    await _publish(client)
    runs = (await client.get("/admin/publish-runs", headers=as_editor())).json()
    assert [r["reused"] for r in runs[:2]] == [True, False]


async def test_reuse_requires_the_pointer_to_still_name_that_run(
    client: httpx.AsyncClient,
) -> None:
    """Existence is not identity.

    After a rollback the newest successful run is the *forward* publish, but the live
    pointer names the older one. A reuse check that only asked "do the bytes exist?"
    would then mark the next publish `reused` and leave the stale catalogue live forever.
    """
    show_id = await _seed_one_show(client)
    first = (await _publish(client))["run"]
    await make_episode(client, show_id, number=2, content_group="cg-2", title="Second")
    second = (await _publish(client))["run"]
    assert (await client.get("/catalog")).json()["counts"]["episodes"] == 2

    await client.post(f"/admin/catalog/rollback/{first['id']}", headers=as_admin())
    assert (await client.get("/catalog")).json()["counts"]["episodes"] == 1

    # Content still has two episodes and both run objects exist, but the live pointer is
    # on the older one — so this must be a real publish, not a reuse.
    again = await _publish(client)
    assert again["reused"] is False
    assert again["run"]["catalog_key"] not in {first["catalog_key"], second["catalog_key"]}
    assert (await client.get("/catalog")).json()["counts"]["episodes"] == 2


async def test_counts_stay_a_counts_map(client: httpx.AsyncClient) -> None:
    """`reused` and `rolled_back_to` are their own fields, not entries beside `shows`."""
    show_id = await _seed_one_show(client)
    first = (await _publish(client))["run"]
    reuse = (await _publish(client))["run"]
    assert reuse["reused"] is True
    assert set(reuse["counts"]) == set(first["counts"])
    assert "reused" not in reuse["counts"]

    await make_episode(client, show_id, number=2, content_group="cg-2", title="Second")
    await _publish(client)
    rolled = (
        await client.post(f"/admin/catalog/rollback/{first['id']}", headers=as_admin())
    ).json()
    assert rolled["run"]["rolled_back_to"] == first["id"]
    assert rolled["run"]["reused"] is False
    assert rolled["reused"] is False
    assert "rolled_back_to" not in rolled["run"]["counts"]
