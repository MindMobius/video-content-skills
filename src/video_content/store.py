from __future__ import annotations

import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any

from .config import configured_home, default_state_root
from .layout import ensure_state_layout, state_paths
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
        paths = state_paths(self.root)
        self.profiles_dir = paths["profiles"]
        self.jobs_dir = paths["jobs"]
        self.cache_dir = paths["cache"] / "media"
        self.locks_dir = paths["locks"]
        self.indexes_dir = paths["indexes"]
        self.meta_dir = paths["meta"]
        self.runs_dir = paths["runs"]
        self.archive_dir = paths["archive"]

    @classmethod
    def from_environment(cls, root: str | Path | None = None) -> Store:
        """Build a store from the one active runtime configuration.

        A direct API caller may not go through the CLI's global config setup.
        Resolve the persisted home here as a final safety net, while keeping an
        explicit root authoritative for isolated tests and temporary work.
        """

        selected = configured_home(explicit_home=root)
        return cls(selected or default_state_root())

    def initialize(self) -> dict[str, Any]:
        ensure_state_layout(self.root)
        return {
            "schema_version": "video-content/store-v1",
            "root": str(self.root),
            "ready": True,
        }

    def run_dir(self, run_id: str, *, create: bool = False) -> Path:
        """Return one run workspace below the canonical ``runs`` directory."""

        selected = ensure_within(
            self.runs_dir, self.runs_dir / safe_id(run_id, label="run id")
        )
        if create:
            selected.mkdir(parents=True, exist_ok=True)
        return selected

    def archive_dir_for(self, name: str, *, create: bool = False) -> Path:
        """Return one explicitly named archive bucket below ``archive``."""

        selected = ensure_within(
            self.archive_dir, self.archive_dir / safe_id(name, label="archive name")
        )
        if create:
            selected.mkdir(parents=True, exist_ok=True)
        return selected

    def save_profile(self, profile: Profile | dict[str, Any]) -> dict[str, Any]:
        self.initialize()
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

    def validate_integrity(self, *, max_errors: int = 20) -> dict[str, Any]:
        """Verify the active Job tree without changing any state."""

        errors: list[dict[str, str]] = []
        jobs_checked = 0
        artifacts_checked = 0
        unreferenced_artifacts = 0

        def add_error(kind: str, path: Path, message: str) -> None:
            if len(errors) < max_errors:
                errors.append(
                    {
                        "kind": kind,
                        "path": str(path),
                        "message": message,
                    }
                )

        if not self.jobs_dir.is_dir():
            add_error("missing_directory", self.jobs_dir, "jobs directory is missing")
        else:
            for job_dir in sorted(self.jobs_dir.iterdir()):
                if not job_dir.is_dir():
                    add_error(
                        "unexpected_entry",
                        job_dir,
                        "jobs contains a non-directory entry",
                    )
                    continue
                jobs_checked += 1
                expected_job_entries = {"job.json", "events.jsonl", "artifacts", "work"}
                for entry in job_dir.iterdir():
                    if entry.name not in expected_job_entries:
                        add_error(
                            "unexpected_job_entry",
                            entry,
                            "job directory contains an ungoverned entry",
                        )
                job_path = job_dir / "job.json"
                events_path = job_dir / "events.jsonl"
                if not job_path.is_file():
                    add_error("missing_job", job_path, "job.json is missing")
                    continue
                if not events_path.is_file():
                    add_error("missing_events", events_path, "events.jsonl is missing")
                try:
                    job = read_json(job_path)
                except (OSError, TypeError, ValueError) as error:
                    add_error("invalid_job", job_path, str(error))
                    continue
                if not isinstance(job, dict):
                    add_error(
                        "invalid_job", job_path, "job.json must contain an object"
                    )
                    continue
                if str(job.get("job_id") or "") != job_dir.name:
                    add_error(
                        "job_id_mismatch",
                        job_path,
                        "job_id does not match directory name",
                    )
                references = job.get("artifact_refs")
                if not isinstance(references, list):
                    add_error(
                        "invalid_artifacts", job_path, "artifact_refs must be a list"
                    )
                    references = []
                referenced_paths: set[Path] = set()
                for reference in references:
                    if not isinstance(reference, dict):
                        add_error(
                            "invalid_artifact_reference",
                            job_path,
                            "artifact reference must be an object",
                        )
                        continue
                    artifact_id = str(reference.get("artifact_id") or "")
                    raw_path = str(reference.get("path") or "")
                    try:
                        target = ensure_within(job_dir, job_dir / raw_path)
                    except (OSError, ValueError) as error:
                        add_error("unsafe_artifact_path", job_path, str(error))
                        continue
                    referenced_paths.add(target)
                    artifacts_checked += 1
                    if not target.is_file():
                        add_error(
                            "missing_artifact",
                            target,
                            f"artifact {artifact_id} is missing",
                        )
                        continue
                    expected_bytes = reference.get("bytes")
                    if (
                        isinstance(expected_bytes, int)
                        and not isinstance(expected_bytes, bool)
                        and target.stat().st_size != expected_bytes
                    ):
                        add_error(
                            "artifact_size_mismatch",
                            target,
                            f"artifact {artifact_id} size mismatch",
                        )
                        continue
                    expected_sha256 = str(reference.get("sha256") or "")
                    if expected_sha256 and sha256_file(target) != expected_sha256:
                        add_error(
                            "artifact_hash_mismatch",
                            target,
                            f"artifact {artifact_id} hash mismatch",
                        )
                artifact_dir = job_dir / "artifacts"
                if artifact_dir.is_dir():
                    for target in artifact_dir.rglob("*"):
                        if (
                            target.is_file()
                            and target.resolve() not in referenced_paths
                        ):
                            unreferenced_artifacts += 1
                            add_error(
                                "unreferenced_artifact",
                                target,
                                "artifact file is not referenced by job.json",
                            )

        index_path = self.indexes_dir / "idempotency.json"
        if index_path.is_file():
            try:
                index = read_json(index_path)
            except (OSError, TypeError, ValueError) as error:
                add_error("invalid_index", index_path, str(error))
            else:
                if not isinstance(index, dict):
                    add_error(
                        "invalid_index",
                        index_path,
                        "idempotency index must be an object",
                    )
                else:
                    for key, job_id in index.items():
                        try:
                            job = self.get_job(str(job_id))
                        except (OSError, ValueError, TypeError) as error:
                            add_error("dangling_index", index_path, f"{key}: {error}")
                            continue
                        if job.get("idempotency_key") != key:
                            add_error(
                                "index_mismatch",
                                index_path,
                                f"{key}: job idempotency key mismatch",
                            )
        return {
            "schema_version": "video-content/state-integrity-v1",
            "root": str(self.root),
            "jobs_checked": jobs_checked,
            "artifacts_checked": artifacts_checked,
            "unreferenced_artifacts": unreferenced_artifacts,
            "errors": errors,
            "error_count": len(errors),
            "status": "passed" if not errors else "failed",
        }

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
