from __future__ import annotations

import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any

from .locking import exclusive_file_lock
from .models import ArtifactRef, Job, Profile
from .util import (
    append_json_line,
    ensure_within,
    new_id,
    read_json,
    reject_secrets,
    safe_id,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_json_atomic,
)


class Store:
    """Durable store for profiles, jobs, immutable artifacts, and events."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.profiles_dir = self.root / "profiles"
        self.jobs_dir = self.root / "jobs"
        self.cache_dir = self.root / "cache" / "media"
        self.locks_dir = self.root / "locks"
        self.indexes_dir = self.root / "indexes"

    @classmethod
    def from_environment(cls, root: str | Path | None = None) -> Store:
        selected = (
            root or os.getenv("VIDEO_CONTENT_HOME") or Path.cwd() / ".video-content"
        )
        return cls(selected)

    def initialize(self) -> dict[str, Any]:
        for path in (
            self.profiles_dir,
            self.jobs_dir,
            self.cache_dir,
            self.locks_dir,
            self.indexes_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return {
            "schema_version": "video-content/store-v1",
            "root": str(self.root),
            "ready": True,
        }

    def save_profile(self, profile: Profile | dict[str, Any]) -> dict[str, Any]:
        document = profile.as_dict() if isinstance(profile, Profile) else dict(profile)
        profile_id = safe_id(str(document["profile_id"]), label="profile id")
        now = utc_now()
        path = self.profiles_dir / f"{profile_id}.json"
        if path.is_file():
            previous = read_json(path)
            document.setdefault("created_at", previous["created_at"])
        else:
            document.setdefault("created_at", now)
        document.setdefault("schema_version", "video-content/profile-v1")
        document.setdefault("baseline", {})
        document.setdefault("settings", {})
        document.setdefault("enabled", True)
        document["updated_at"] = now
        reject_secrets(document)
        with exclusive_file_lock(path):
            write_json_atomic(path, document)
        return document

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        path = self.profiles_dir / f"{safe_id(profile_id, label='profile id')}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Profile not found: {profile_id}")
        return read_json(path)

    def list_profiles(self) -> list[dict[str, Any]]:
        if not self.profiles_dir.is_dir():
            return []
        return [read_json(path) for path in sorted(self.profiles_dir.glob("*.json"))]

    def create_job(
        self,
        *,
        source: dict[str, Any],
        idempotency_key: str,
        run_id: str | None = None,
        profile_id: str | None = None,
        job_id: str | None = None,
        initial_status: str = "queued",
        initial_stage: str = "queued",
    ) -> tuple[dict[str, Any], bool]:
        self.initialize()
        safe_id(idempotency_key, label="idempotency key")
        index_path = self.indexes_dir / "idempotency.json"
        with exclusive_file_lock(index_path):
            index = read_json(index_path) if index_path.is_file() else {}
            existing = index.get(idempotency_key)
            if existing:
                return self.get_job(existing), True
            selected_job_id = safe_id(job_id or new_id("job"), label="job id")
            job = Job(
                job_id=selected_job_id,
                run_id=run_id,
                profile_id=profile_id,
                idempotency_key=idempotency_key,
                source=source,
                status=initial_status,
                stage=initial_stage,
                created_at=utc_now(),
                updated_at=utc_now(),
            ).as_dict()
            reject_secrets(job)
            job_dir = self.job_dir(selected_job_id)
            job_dir.mkdir(parents=True, exist_ok=False)
            write_json_atomic(job_dir / "job.json", job)
            append_json_line(
                job_dir / "events.jsonl",
                {
                    "at": job["created_at"],
                    "type": "job.created",
                    "status": initial_status,
                    "stage": initial_stage,
                },
            )
            index[idempotency_key] = selected_job_id
            write_json_atomic(index_path, dict(sorted(index.items())))
            return job, False

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self.job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError(f"Job not found: {job_id}")
        return read_json(path)

    def write_job(self, document: dict[str, Any]) -> dict[str, Any]:
        job_id = safe_id(str(document["job_id"]), label="job id")
        path = self.job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError(f"Job not found: {job_id}")
        reject_secrets(document)
        with exclusive_file_lock(path):
            document = dict(document)
            document["updated_at"] = utc_now()
            write_json_atomic(path, document)
        return document

    def list_jobs(
        self,
        *,
        run_id: str | None = None,
        status: str | None = None,
        profile_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.jobs_dir.is_dir():
            return []
        jobs: list[dict[str, Any]] = []
        for path in sorted(self.jobs_dir.glob("*/job.json")):
            document = read_json(path)
            if run_id is not None and document.get("run_id") != run_id:
                continue
            if status is not None and document.get("status") != status:
                continue
            if profile_id is not None and document.get("profile_id") != profile_id:
                continue
            jobs.append(document)
        return jobs

    def append_event(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        document = {"at": utc_now(), **event}
        reject_secrets(document)
        path = self.job_dir(job_id) / "events.jsonl"
        with exclusive_file_lock(path):
            append_json_line(path, document)
        return document

    def put_artifact(
        self,
        job_id: str,
        *,
        kind: str,
        data: bytes | str | dict[str, Any] | list[Any] | None = None,
        source_path: str | Path | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if (data is None) == (source_path is None):
            raise ValueError("Provide exactly one of data or source_path")
        job = self.get_job(job_id)
        safe_id(kind, label="artifact kind")
        metadata = dict(metadata or {})
        reject_secrets(metadata)
        if source_path is not None:
            selected = Path(source_path).expanduser().resolve()
            if not selected.is_file():
                raise FileNotFoundError(f"Artifact source does not exist: {selected}")
            digest = sha256_file(selected)
            size = selected.stat().st_size
            payload: bytes | None = None
            original_name = filename or selected.name
        else:
            if isinstance(data, str):
                payload = data.encode("utf-8")
            elif isinstance(data, (dict, list)):
                reject_secrets(data)
                payload = (
                    json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                    + b"\n"
                )
            else:
                payload = bytes(data or b"")
            digest = sha256_bytes(payload)
            size = len(payload)
            original_name = filename or f"{kind}.bin"
        suffix = Path(original_name).suffix.lower()
        artifact_key = sha256_bytes(f"{kind}\0{digest}".encode())
        artifact_id = f"art_{artifact_key[:24]}"
        relative = Path("artifacts") / kind / f"{artifact_id}{suffix}"
        target = ensure_within(self.job_dir(job_id), self.job_dir(job_id) / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha256_file(target) != digest:
                raise ValueError(f"Immutable artifact collision: {target}")
        elif source_path is not None:
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(selected, temporary)
            if sha256_file(temporary) != digest:
                temporary.unlink(missing_ok=True)
                raise ValueError("Artifact changed while being copied")
            os.replace(temporary, target)
        else:
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(payload or b"")
            os.replace(temporary, target)
        detected_type = media_type or mimetypes.guess_type(original_name)[0]
        reference = ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            path=relative.as_posix(),
            sha256=digest,
            bytes=size,
            media_type=detected_type,
            created_at=utc_now(),
            metadata=metadata,
        ).as_dict()
        refs = list(job.get("artifact_refs", []))
        existing = next(
            (item for item in refs if item["artifact_id"] == artifact_id), None
        )
        if existing is not None:
            if existing != reference:
                # Creation timestamps may differ across an idempotent retry.
                normalized_existing = {
                    **existing,
                    "created_at": reference.get("created_at"),
                }
                if normalized_existing != reference:
                    raise ValueError(f"Artifact reference mismatch: {artifact_id}")
            return existing
        refs.append(reference)
        job["artifact_refs"] = refs
        self.write_job(job)
        self.append_event(job_id, {"type": "artifact.saved", "artifact": reference})
        return reference

    def list_artifacts(
        self, job_id: str, *, kind: str | None = None
    ) -> list[dict[str, Any]]:
        refs = list(self.get_job(job_id).get("artifact_refs", []))
        if kind is not None:
            refs = [item for item in refs if item.get("kind") == kind]
        return refs

    def read_artifact(
        self, job_id: str, artifact_id: str
    ) -> tuple[dict[str, Any], bytes]:
        safe_id(artifact_id, label="artifact id")
        reference = next(
            (
                item
                for item in self.list_artifacts(job_id)
                if item["artifact_id"] == artifact_id
            ),
            None,
        )
        if reference is None:
            raise FileNotFoundError(f"Artifact not found: {artifact_id}")
        path = ensure_within(
            self.job_dir(job_id), self.job_dir(job_id) / reference["path"]
        )
        if not path.is_file() or sha256_file(path) != reference["sha256"]:
            raise ValueError(f"Artifact integrity check failed: {artifact_id}")
        return reference, path.read_bytes()

    def save_document(
        self,
        job_id: str,
        *,
        kind: str,
        document: dict[str, Any],
        identifier_field: str,
        identifier_prefix: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = dict(document)
        payload.setdefault(identifier_field, new_id(identifier_prefix))
        payload.setdefault("job_id", job_id)
        payload.setdefault("created_at", utc_now())
        reject_secrets(payload)
        reference = self.put_artifact(
            job_id,
            kind=kind,
            data=payload,
            filename=f"{payload[identifier_field]}.json",
            media_type="application/json",
            metadata={identifier_field: payload[identifier_field]},
        )
        return payload, reference

    def read_json_artifact(self, job_id: str, artifact_id: str) -> dict[str, Any]:
        _, raw = self.read_artifact(job_id, artifact_id)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("JSON artifact must contain an object")
        return value

    def job_dir(self, job_id: str) -> Path:
        selected = self.jobs_dir / safe_id(job_id, label="job id")
        return ensure_within(self.jobs_dir, selected)
