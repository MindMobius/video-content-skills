"""Persistent automation profiles and bounded WeChat draft authorization."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import read_json, utc_now, write_json_atomic

PROFILE_SCHEMA_VERSION = "video-automation/profile-v1"
AUTHORIZATION_SCHEMA_VERSION = "video-automation/draft-authorization-v1"
PROHIBITED_ACTIONS = {
    "publish",
    "mass_send",
    "schedule",
    "originality",
    "account_management",
}
SECRET_KEY_RE = re.compile(
    r"(?i)(cookie|token|password|browser_storage|clipboard_payload|base64)"
)


def save_automation_profile(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist one versioned Watch Later automation profile."""
    path = path.expanduser().resolve()
    candidate = copy.deepcopy(document)
    _reject_secrets(candidate)
    identity = _profile_identity(candidate)
    existing: dict[str, Any] | None = None
    if path.is_file():
        existing = read_automation_profile(path)
    now = utc_now()
    if existing is not None:
        previous_identity = _profile_identity(existing)
        if previous_identity == identity:
            return existing
        profile_id = str(existing["profile_id"])
        version = int(existing["version"]) + 1
        created_at = str(existing.get("created_at") or now)
    else:
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        profile_id = str(candidate.get("profile_id") or f"profile_{digest[:16]}")
        version = int(candidate.get("version") or 1)
        created_at = str(candidate.get("created_at") or now)
    result = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "version": version,
        "enabled": bool(candidate.get("enabled", True)),
        "source": copy.deepcopy(candidate.get("source")),
        "content": copy.deepcopy(candidate.get("content")),
        "evidence_policy": copy.deepcopy(candidate.get("evidence_policy")),
        "retry_policy": copy.deepcopy(candidate.get("retry_policy")),
        "draft_authorization_id": str(
            candidate.get("draft_authorization_id") or ""
        ).strip(),
        "prohibited_actions": list(candidate.get("prohibited_actions") or []),
        "created_at": created_at,
        "updated_at": now,
    }
    _validate_profile(result)
    write_json_atomic(path, result)
    return {**result, "profile_path": str(path)}


def read_automation_profile(path: Path) -> dict[str, Any]:
    path = _require_file(path, "Automation profile")
    document = read_json(path)
    _reject_secrets(document)
    _validate_profile(document)
    return {**document, "profile_path": str(path)}


def save_draft_authorization(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Persist a revocable authorization limited to saving WeChat drafts."""
    path = path.expanduser().resolve()
    candidate = copy.deepcopy(document)
    _reject_secrets(candidate)
    now = utc_now()
    authorization_id = str(candidate.get("authorization_id") or "").strip()
    if not authorization_id:
        identity = {
            "profile_ids": candidate.get("profile_ids"),
            "browser_profile_alias": candidate.get("browser_profile_alias"),
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        authorization_id = f"auth_{digest[:16]}"
    result = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "status": str(candidate.get("status") or "active").strip(),
        "profile_ids": list(candidate.get("profile_ids") or []),
        "browser_profile_alias": str(
            candidate.get("browser_profile_alias") or ""
        ).strip(),
        "allowed_actions": list(candidate.get("allowed_actions") or []),
        "prohibited_actions": list(candidate.get("prohibited_actions") or []),
        "created_at": str(candidate.get("created_at") or now),
        "expires_at": candidate.get("expires_at"),
        "revoked_at": candidate.get("revoked_at"),
    }
    _validate_authorization(result)
    write_json_atomic(path, result)
    return {**result, "authorization_path": str(path)}


def read_draft_authorization(path: Path) -> dict[str, Any]:
    path = _require_file(path, "Draft authorization")
    document = read_json(path)
    _reject_secrets(document)
    _validate_authorization(document)
    return {**document, "authorization_path": str(path)}


def require_active_draft_authorization(
    profile: dict[str, Any], authorization: dict[str, Any]
) -> None:
    _validate_profile(profile)
    _validate_authorization(authorization)
    if authorization["status"] != "active":
        raise ValueError("Draft authorization is not active")
    if profile["profile_id"] not in authorization["profile_ids"]:
        raise ValueError("Draft authorization does not cover this automation profile")
    if profile["draft_authorization_id"] != authorization["authorization_id"]:
        raise ValueError("Automation profile references a different authorization")
    expires_at = authorization.get("expires_at")
    if expires_at is not None and _parse_timestamp(str(expires_at)) <= datetime.now(
        timezone.utc
    ):
        raise ValueError("Draft authorization has expired")


def _profile_identity(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(document.get("enabled", True)),
        "source": document.get("source"),
        "content": document.get("content"),
        "evidence_policy": document.get("evidence_policy"),
        "retry_policy": document.get("retry_policy"),
        "draft_authorization_id": document.get("draft_authorization_id"),
        "prohibited_actions": document.get("prohibited_actions"),
    }


def _validate_profile(document: Any) -> None:
    if not isinstance(document, dict):
        raise TypeError("Automation profile must be a JSON object")
    if document.get("schema_version") not in {None, PROFILE_SCHEMA_VERSION}:
        raise ValueError("Unsupported automation profile schema")
    source = document.get("source")
    content = document.get("content")
    evidence = document.get("evidence_policy")
    retry = document.get("retry_policy")
    if not isinstance(source, dict) or source.get("kind") != "bilibili_watch_later":
        raise ValueError("Automation profile source must be bilibili_watch_later")
    if not str(source.get("account_profile_alias") or "").strip():
        raise ValueError("Automation profile requires a Bilibili profile alias")
    if int(source.get("poll_interval_seconds") or 0) < 60:
        raise ValueError("Automation poll interval must be at least 60 seconds")
    if not isinstance(content, dict) or content.get("medium") != "wechat_article":
        raise ValueError("Automation content medium must be wechat_article")
    if content.get("image_policy") != "source_video_only":
        raise ValueError("Automation images must use source_video_only")
    for field in ("objective", "output_language", "style"):
        if not str(content.get(field) or "").strip():
            raise ValueError(f"Automation content {field} cannot be empty")
    if (
        not isinstance(evidence, dict)
        or evidence.get("require_hard_subtitle_assessment") is not True
    ):
        raise ValueError("Automation must require hard subtitle assessment")
    if not any(
        evidence.get(field) is True
        for field in ("allow_platform_subtitle", "allow_hard_ocr", "allow_audio_asr")
    ):
        raise ValueError("Automation must allow at least one subtitle evidence source")
    if not isinstance(retry, dict):
        raise TypeError("Automation retry policy must be an object")
    for field, maximum in (
        ("max_technical_attempts", 20),
        ("max_content_repairs", 10),
        ("backoff_seconds", 86400),
    ):
        value = retry.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Automation retry policy {field} is invalid")
        if value > maximum:
            raise ValueError(f"Automation retry policy {field} is too large")
    if not re.fullmatch(
        r"profile[-_][A-Za-z0-9_-]+", str(document.get("profile_id") or "")
    ):
        raise ValueError("Automation profile_id is invalid")
    if not isinstance(document.get("version"), int) or document["version"] < 1:
        raise ValueError("Automation profile version is invalid")
    if not re.fullmatch(
        r"auth[-_][A-Za-z0-9_-]+",
        str(document.get("draft_authorization_id") or ""),
    ):
        raise ValueError("Automation draft_authorization_id is invalid")
    _require_prohibited_actions(document.get("prohibited_actions"))


def _validate_authorization(document: Any) -> None:
    if not isinstance(document, dict):
        raise TypeError("Draft authorization must be a JSON object")
    if document.get("schema_version") not in {None, AUTHORIZATION_SCHEMA_VERSION}:
        raise ValueError("Unsupported draft authorization schema")
    if not re.fullmatch(
        r"auth[-_][A-Za-z0-9_-]+", str(document.get("authorization_id") or "")
    ):
        raise ValueError("Draft authorization_id is invalid")
    if document.get("status") not in {"active", "revoked"}:
        raise ValueError("Draft authorization status is invalid")
    profile_ids = document.get("profile_ids")
    if not isinstance(profile_ids, list) or not profile_ids:
        raise ValueError("Draft authorization requires profile IDs")
    if len(set(map(str, profile_ids))) != len(profile_ids):
        raise ValueError("Draft authorization profile IDs must be unique")
    if not str(document.get("browser_profile_alias") or "").strip():
        raise ValueError("Draft authorization requires a browser profile alias")
    if document.get("allowed_actions") != ["save_wechat_draft"]:
        raise ValueError("Draft authorization may only allow saving a draft")
    _require_prohibited_actions(document.get("prohibited_actions"))
    if document["status"] == "revoked" and not document.get("revoked_at"):
        raise ValueError("Revoked draft authorization requires revoked_at")
    for field in ("created_at", "expires_at", "revoked_at"):
        value = document.get(field)
        if value is not None:
            _parse_timestamp(str(value))


def _require_prohibited_actions(value: Any) -> None:
    if not isinstance(value, list) or set(map(str, value)) != PROHIBITED_ACTIONS:
        raise ValueError("Automation prohibited actions are incomplete")


def _reject_secrets(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                raise ValueError(
                    f"Automation documents must not persist secret field: {path}.{key}"
                )
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if re.search(r"(?i)(?:[?&](?:token|cookie|sessdata|password)=)", value):
            raise ValueError("Automation documents must not persist secret URL values")
        if value.startswith("data:") and ";base64," in value[:100].lower():
            raise ValueError("Automation documents must not persist Base64 payloads")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid ISO timestamp: {value}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path
