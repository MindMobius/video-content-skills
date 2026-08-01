from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from .core.util import (
    local_job_id,
    read_json,
    safe_job_id,
    utc_now,
    write_json_atomic,
)
from .pipeline import ExtractionPipeline, ExtractionRequest
from .platforms.bilibili import OpenCliClient, OpenCliSettings


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.jobs_dir = self.root / "jobs"

    @classmethod
    def from_environment(cls, root: str | Path | None = None) -> JobStore:
        selected = (
            root
            or os.getenv("VIDEO_SUBTITLE_HOME")
            or os.getenv("SUBTITLE_AGENT_HOME")
            or Path.cwd() / ".video-subtitle"
        )
        return cls(Path(selected))

    def start(
        self,
        request: ExtractionRequest,
        settings: OpenCliSettings,
    ) -> dict[str, Any]:
        job_id = local_job_id()
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        job_request = replace(request, output_dir=job_dir)
        request_path = job_dir / "request.json"
        document = {
            "schema_version": "video-subtitle/request-v1",
            "job_id": job_id,
            "connection": settings.as_dict(),
            "extraction": job_request.as_dict(),
        }
        write_json_atomic(request_path, document)

        manifest_path = job_dir / "manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": "video-subtitle/v1",
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "request": job_request.as_dict(),
            "video": None,
            "selected_source": None,
            "sources": [],
            "review": None,
            "attempts": [],
            "artifacts": [],
            "warnings": [],
            "error": None,
            "next_action": None,
        }
        write_json_atomic(manifest_path, manifest)

        stdout_path = job_dir / "worker.stdout.log"
        stderr_path = job_dir / "worker.stderr.log"
        command = [
            sys.executable,
            "-m",
            "video_subtitle.cli",
            "_worker",
            "--request-file",
            str(request_path),
        ]
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "DETACHED_PROCESS", 0)
        try:
            with (
                stdout_path.open("w", encoding="utf-8") as stdout,
                stderr_path.open("w", encoding="utf-8") as stderr,
            ):
                process = subprocess.Popen(
                    command,
                    stdout=stdout,
                    stderr=stderr,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=creation_flags,
                )
        except OSError as error:
            manifest["status"] = "failed"
            manifest["stage"] = "launch_worker"
            manifest["updated_at"] = utc_now()
            manifest["finished_at"] = utc_now()
            manifest["error"] = {
                "code": "WORKER_LAUNCH_FAILED",
                "message": str(error),
            }
            write_json_atomic(manifest_path, manifest)
            return manifest

        current = read_json(manifest_path)
        if current.get("status") == "queued":
            current["worker_pid"] = process.pid
            current["updated_at"] = utc_now()
            write_json_atomic(manifest_path, current)
        return current

    def get(self, job_id: str) -> dict[str, Any]:
        job_id = safe_job_id(job_id)
        manifest_path = self.jobs_dir / job_id / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Subtitle job not found: {job_id}")
        manifest = read_json(manifest_path)
        job_dir = manifest_path.parent
        manifest["job_directory"] = str(job_dir)
        for log_name in ("worker.stdout.log", "worker.stderr.log"):
            log_path = job_dir / log_name
            if log_path.exists():
                manifest.setdefault("worker_logs", {})[log_name] = str(log_path)
        return manifest


def run_worker_request(request_file: Path) -> dict[str, Any]:
    document = read_json(request_file.resolve())
    settings = OpenCliSettings.from_dict(document["connection"])
    request = ExtractionRequest.from_dict(document["extraction"])
    client = OpenCliClient(settings)
    pipeline = ExtractionPipeline(client)
    return pipeline.run(request, job_id=str(document["job_id"]))
