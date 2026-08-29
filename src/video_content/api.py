from __future__ import annotations

import base64
from typing import Any

from .automation import save_watch_later_profile
from .automation import watch_later_scan as scan_watch_later
from .config import apply_configuration, update_configuration
from .content import content_save as save_content
from .content import content_validate as validate_content
from .content import transcript_save as save_transcript
from .diagnostics import doctor as run_doctor
from .environment import normalize_capabilities
from .evidence import evidence_start as start_evidence
from .evidence import source_inspect as inspect_source
from .jobs import update_job as transition_job
from .platforms.bilibili import OpenCliClient, OpenCliSettings
from .platforms.watch_later import OpenCliWatchLaterSource
from .store import Store
from .wechat import wechat_bind as bind_wechat
from .wechat import wechat_prepare as prepare_wechat


def system_setup(
    capabilities: list[str] | None = None,
    *,
    config_path: str | None = None,
) -> dict[str, Any]:
    report = system_doctor(capabilities, deep=False, config_path=config_path)
    return report["setup"]


def system_configure(
    values: dict[str, str | None],
    *,
    clear: list[str] | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    return update_configuration(values, clear=clear, path=config_path)


def system_doctor(
    capabilities: list[str] | None = None,
    *,
    deep: bool = True,
    config_path: str | None = None,
) -> dict[str, Any]:
    apply_configuration(config_path)
    selected = normalize_capabilities(capabilities)
    settings = OpenCliSettings.discover(allow_missing=True)
    return run_doctor(
        OpenCliClient(settings),
        capabilities=selected,
        deep=deep,
        config_path=config_path,
    )


def source_inspect(
    url: str,
    page: int | None = None,
    *,
    config_path: str | None = None,
) -> dict[str, Any]:
    settings = _settings(config_path)
    return inspect_source(url, page=page, settings=settings)


def evidence_start(
    url: str,
    *,
    home: str | None = None,
    page: int | None = None,
    run_id: str | None = None,
    profile_id: str | None = None,
    language: str = "ai-zh",
    ocr_backend: str = "auto",
    asr_backend: str = "none",
    video_path: str | None = None,
    download_if_needed: bool = True,
    collect_all_sources: bool = False,
    media_execution: str = "auto",
    hard_subtitle_visual_decision: str = "not_assessed",
    visual_assessment: dict[str, Any] | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    return start_evidence(
        _store(home, config_path),
        url=url,
        page=page,
        run_id=run_id,
        profile_id=profile_id,
        language=language,
        ocr_backend=ocr_backend,
        asr_backend=asr_backend,
        video_path=video_path,
        download_if_needed=download_if_needed,
        collect_all_sources=collect_all_sources,
        media_execution=media_execution,
        hard_subtitle_visual_decision=hard_subtitle_visual_decision,
        visual_assessment=visual_assessment,
        settings=_settings(config_path),
    )


def job_get(job_id: str, *, home: str | None = None) -> dict[str, Any]:
    return _store(home).get_job(job_id)


def artifact_list(
    job_id: str, *, home: str | None = None, kind: str | None = None
) -> dict[str, Any]:
    artifacts = _store(home).list_artifacts(job_id, kind=kind)
    return {
        "schema_version": "video-content/artifact-list-v1",
        "job_id": job_id,
        "artifacts": artifacts,
    }


def artifact_read(
    job_id: str,
    artifact_id: str,
    *,
    home: str | None = None,
    text: bool = True,
) -> dict[str, Any]:
    reference, payload = _store(home).read_artifact(job_id, artifact_id)
    if text:
        try:
            content = payload.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = base64.b64encode(payload).decode("ascii")
            encoding = "base64"
    else:
        content = base64.b64encode(payload).decode("ascii")
        encoding = "base64"
    return {
        "schema_version": "video-content/artifact-read-v1",
        "job_id": job_id,
        "artifact": reference,
        "encoding": encoding,
        "content": content,
    }


def transcript_save(
    job_id: str,
    evidence_ids: list[str],
    cues: list[dict[str, Any]],
    text: str,
    *,
    home: str | None = None,
    corrections: list[dict[str, Any]] | None = None,
    uncertainties: list[dict[str, Any]] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return save_transcript(
        _store(home),
        job_id=job_id,
        evidence_ids=evidence_ids,
        cues=cues,
        text=text,
        corrections=corrections,
        uncertainties=uncertainties,
        quality=quality,
    )


def content_save(
    job_id: str,
    transcript_id: str,
    carrier: str,
    document: dict[str, Any],
    *,
    home: str | None = None,
    media: list[dict[str, Any]] | None = None,
    audit: dict[str, Any] | None = None,
    render: bool = True,
) -> dict[str, Any]:
    return save_content(
        _store(home),
        job_id=job_id,
        transcript_id=transcript_id,
        carrier=carrier,
        document=document,
        media=media,
        audit=audit,
        render=render,
    )


def content_validate(
    job_id: str, content_id: str, *, home: str | None = None
) -> dict[str, Any]:
    return validate_content(_store(home), job_id=job_id, content_id=content_id)


def watch_later_scan(
    profile_id: str,
    *,
    home: str | None = None,
    account_profile_alias: str | None = None,
    carrier: str = "wechat_article",
    limit: int | None = None,
    baseline_if_empty: bool = False,
    config_path: str | None = None,
) -> dict[str, Any]:
    store = _store(home, config_path)
    try:
        profile = store.get_profile(profile_id)
    except FileNotFoundError:
        if not account_profile_alias:
            raise ValueError(
                "account_profile_alias is required when creating a Watch Later profile"
            ) from None
        profile = save_watch_later_profile(
            store,
            profile_id=profile_id,
            account_profile_alias=account_profile_alias,
            carrier=carrier,
        )
    alias = str(profile["source"]["account_profile_alias"])
    settings = _settings(config_path, profile=alias)
    source = OpenCliWatchLaterSource(OpenCliClient(settings))
    return scan_watch_later(
        store,
        profile_id=profile_id,
        source=source,
        limit=limit,
        baseline_if_empty=baseline_if_empty,
    )


def job_list(
    *,
    home: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    jobs = _store(home).list_jobs(run_id=run_id, status=status, profile_id=profile_id)
    return {
        "schema_version": "video-content/job-list-v1",
        "jobs": jobs,
        "count": len(jobs),
    }


def job_update(
    job_id: str,
    *,
    home: str | None = None,
    stage: str | None = None,
    status: str | None = None,
    error: dict[str, Any] | None = None,
    retry_at: str | None = None,
    increment_attempts: bool = False,
) -> dict[str, Any]:
    return transition_job(
        _store(home),
        job_id,
        stage=stage,
        status=status,
        error=error,
        retry_at=retry_at,
        increment_attempts=increment_attempts,
    )


def wechat_prepare(
    job_id: str,
    content_id: str,
    *,
    home: str | None = None,
    authorized: bool,
    save_draft: bool,
    copy_to_clipboard: bool = False,
    replace_existing_draft: bool = False,
) -> dict[str, Any]:
    return prepare_wechat(
        _store(home),
        job_id=job_id,
        content_id=content_id,
        authorized=authorized,
        save_draft=save_draft,
        copy_to_clipboard=copy_to_clipboard,
        replace_existing_draft=replace_existing_draft,
    )


def wechat_bind(
    job_id: str,
    content_id: str,
    observation: dict[str, Any],
    *,
    home: str | None = None,
    supersedes_receipt_id: str | None = None,
) -> dict[str, Any]:
    return bind_wechat(
        _store(home),
        job_id=job_id,
        content_id=content_id,
        observation=observation,
        supersedes_receipt_id=supersedes_receipt_id,
    )


def _store(
    home: str | None = None,
    config_path: str | None = None,
) -> Store:
    if config_path is not None:
        apply_configuration(config_path)
    return Store.from_environment(home)


def _settings(
    config_path: str | None, *, profile: str | None = None
) -> OpenCliSettings:
    apply_configuration(config_path)
    return OpenCliSettings.discover(profile=profile)
