from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

PROFILE_SCHEMA = "video-content/profile-v1"
JOB_SCHEMA = "video-content/job-v1"
EVIDENCE_SCHEMA = "video-content/evidence-v1"
TRANSCRIPT_SCHEMA = "video-content/transcript-v1"
CONTENT_SCHEMA = "video-content/content-v1"
DRAFT_RECEIPT_SCHEMA = "video-content/draft-receipt-v1"

JOB_STATUSES = {
    "queued",
    "running",
    "retryable",
    "paused_auth",
    "unprocessable",
    "completed",
    "failed",
}
JOB_STAGES = {
    "queued",
    "inspecting",
    "evidence",
    "transcript",
    "content",
    "handoff",
    "completed",
}
TERMINAL_STATUSES = {"unprocessable", "completed", "failed"}


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    path: str
    sha256: str
    bytes: int
    media_type: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Profile:
    profile_id: str
    source: dict[str, Any]
    carrier: str
    baseline: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = PROFILE_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Job:
    job_id: str
    idempotency_key: str
    source: dict[str, Any]
    stage: str = "queued"
    status: str = "queued"
    run_id: str | None = None
    profile_id: str | None = None
    attempts: int = 0
    retry_at: str | None = None
    last_error: dict[str, Any] | None = None
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    schema_version: str = JOB_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Evidence:
    job_id: str
    source: dict[str, Any]
    observations: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]]
    decision: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    evidence_id: str = ""
    schema_version: str = EVIDENCE_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Transcript:
    job_id: str
    evidence_ids: list[str]
    cues: list[dict[str, Any]]
    text: str
    corrections: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    transcript_id: str = ""
    schema_version: str = TRANSCRIPT_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class Content:
    job_id: str
    transcript_id: str
    carrier: str
    document: dict[str, Any]
    media: list[dict[str, Any]] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    content_id: str = ""
    schema_version: str = CONTENT_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


@dataclass
class DraftReceipt:
    job_id: str
    content_id: str
    platform: str
    draft_identity: dict[str, Any]
    observation: dict[str, Any]
    published: bool = False
    saved_at: str = ""
    receipt_id: str = ""
    schema_version: str = DRAFT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.published is not False:
            raise ValueError("Draft receipts must state published=false")

    def as_dict(self) -> dict[str, Any]:
        return _compact(asdict(self))


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value
