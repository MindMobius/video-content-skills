from __future__ import annotations

from pathlib import Path

import pytest

from video_content.store import Store


def test_initialize_creates_the_canonical_state_layout(tmp_path: Path) -> None:
    store = Store(tmp_path)

    result = store.initialize()

    assert result["ready"] is True
    for relative in (
        "profiles",
        "jobs",
        "cache/media",
        "indexes",
        "locks",
        "meta",
        "runs",
        "archive",
    ):
        assert (tmp_path / Path(*relative.split("/"))).is_dir()


def test_run_and_archive_helpers_stay_below_governed_directories(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)

    run = store.run_dir("run_example", create=True)
    archive = store.archive_dir_for("2026-08-29-cleanup", create=True)

    assert run == (tmp_path / "runs" / "run_example").resolve()
    assert archive == (tmp_path / "archive" / "2026-08-29-cleanup").resolve()
    assert run.is_dir()
    assert archive.is_dir()


def test_validate_integrity_rejects_unexpected_job_entries(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1layout"},
        idempotency_key="layout",
    )
    (store.job_dir(job["job_id"]) / "notes.txt").write_text(
        "temporary", encoding="utf-8"
    )

    report = store.validate_integrity()

    assert report["status"] == "failed"
    assert any(error["kind"] == "unexpected_job_entry" for error in report["errors"])


def test_validate_integrity_checks_job_artifacts_and_index(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1integrity"},
        idempotency_key="integrity",
    )
    store.put_artifact(
        job["job_id"],
        kind="fixture",
        data="ok",
        filename="fixture.txt",
    )

    report = store.validate_integrity()

    assert report["status"] == "passed"
    assert report["jobs_checked"] == 1
    assert report["artifacts_checked"] == 1
    assert report["unreferenced_artifacts"] == 0


def test_job_creation_is_idempotent_and_queryable(tmp_path: Path) -> None:
    store = Store(tmp_path)
    first, reused = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1example", "page": 1},
        idempotency_key="bilibili_BV1example_p1",
        run_id="run_1",
        profile_id="daily",
    )
    second, reused_second = store.create_job(
        source={"platform": "bilibili", "bvid": "BV1example", "page": 1},
        idempotency_key="bilibili_BV1example_p1",
    )
    assert reused is False
    assert reused_second is True
    assert second["job_id"] == first["job_id"]
    assert [job["job_id"] for job in store.list_jobs(run_id="run_1")] == [
        first["job_id"]
    ]


def test_artifacts_are_immutable_and_integrity_checked(tmp_path: Path) -> None:
    store = Store(tmp_path)
    job, _ = store.create_job(source={"kind": "local"}, idempotency_key="local_fixture")
    first = store.put_artifact(
        job["job_id"], kind="platform_subtitle", data="first", filename="subtitle.srt"
    )
    same = store.put_artifact(
        job["job_id"], kind="platform_subtitle", data="first", filename="subtitle.srt"
    )
    assert same["artifact_id"] == first["artifact_id"]
    reference, raw = store.read_artifact(job["job_id"], first["artifact_id"])
    assert reference["sha256"] == first["sha256"]
    assert raw == b"first"
    path = store.job_dir(job["job_id"]) / first["path"]
    path.write_text("mutated", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        store.read_artifact(job["job_id"], first["artifact_id"])


def test_store_rejects_secret_fields_and_path_escape(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with pytest.raises(ValueError, match="secret-like"):
        store.save_profile(
            {
                "profile_id": "daily",
                "source": {"token": "nope"},
                "carrier": "wechat_article",
            }
        )
    with pytest.raises(ValueError, match="Invalid job id"):
        store.job_dir("../outside")
