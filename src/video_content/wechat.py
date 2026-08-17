from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .content import content_validate, get_content
from .jobs import update_job
from .models import DRAFT_RECEIPT_SCHEMA, DraftReceipt
from .store import Store
from .util import reject_secrets, sha256_bytes, utc_now
from .wechat_adapter import prepare_wechat_clipboard

OBSERVATION_SCHEMA = "video-content/wechat-editor-observation-v1"


def wechat_prepare(
    store: Store,
    *,
    job_id: str,
    content_id: str,
    authorized: bool,
    save_draft: bool,
    copy_to_clipboard: bool = False,
) -> dict[str, Any]:
    if authorized is not True or save_draft is not True:
        raise PermissionError(
            "WeChat draft handoff requires explicit authorization to save a draft"
        )
    content = get_content(store, job_id, content_id)
    if content.get("carrier") != "wechat_article":
        raise ValueError("WeChat handoff requires wechat_article content")
    validation = content_validate(store, job_id=job_id, content_id=content_id)
    if validation["valid"] is not True:
        raise ValueError("WeChat handoff requires validated content")
    if store.list_artifacts(job_id, kind="draft_receipt"):
        raise ValueError("This job already has a validated WeChat draft receipt")
    package_dir = _materialize_render_package(store, job_id, content)
    transport = prepare_wechat_clipboard(package_dir, copy=copy_to_clipboard)
    content_reference = _product_reference(
        store, job_id, "content", "content_id", content_id
    )
    current = store.get_job(job_id)
    if current["stage"] == "content":
        current = update_job(store, job_id, stage="handoff", status="running")
    return {
        "schema_version": "video-content/wechat-handoff-v1",
        "job_id": job_id,
        "content_id": content_id,
        "content_sha256": content_reference["sha256"],
        "package_dir": str(package_dir),
        "article_html": str(package_dir / "article.html"),
        "intended_images": transport["marker_count"],
        "clipboard": transport,
        "authorization": {"save_draft": True, "publish": False},
        "job": current,
    }


def wechat_bind(
    store: Store,
    *,
    job_id: str,
    content_id: str,
    observation: dict[str, Any],
) -> dict[str, Any]:
    if store.list_artifacts(job_id, kind="draft_receipt"):
        raise ValueError("This job already has a validated WeChat draft receipt")
    content = get_content(store, job_id, content_id)
    validation = content_validate(store, job_id=job_id, content_id=content_id)
    if validation["valid"] is not True:
        raise ValueError("Cannot bind a draft receipt to invalid content")
    content_reference = _product_reference(
        store, job_id, "content", "content_id", content_id
    )
    normalized = validate_editor_observation(
        observation,
        expected_title=str(content.get("document", {}).get("title") or ""),
        expected_content_sha256=content_reference["sha256"],
    )
    appmsgid = normalized["draft_identity"]["appmsgid"]
    receipt_id = _receipt_id(content_id, appmsgid)
    receipt = DraftReceipt(
        receipt_id=receipt_id,
        job_id=job_id,
        content_id=content_id,
        platform="wechat_official_account",
        draft_identity={
            "appmsgid": appmsgid,
            "content_sha256": content_reference["sha256"],
            "unique": True,
            "refresh_read_back": True,
        },
        observation=normalized,
        published=False,
        saved_at=normalized["saved_at"],
        schema_version=DRAFT_RECEIPT_SCHEMA,
    ).as_dict()
    saved, reference = store.save_document(
        job_id,
        kind="draft_receipt",
        document=receipt,
        identifier_field="receipt_id",
        identifier_prefix="receipt",
    )
    current = store.get_job(job_id)
    if current["stage"] != "handoff":
        current = update_job(store, job_id, stage="handoff", status="running")
    current = update_job(store, job_id, stage="completed", status="completed")
    return {
        "receipt": saved,
        "artifact": reference,
        "validation": validate_draft_receipt(
            store, job_id=job_id, receipt_id=receipt_id
        ),
        "job": current,
    }


def validate_editor_observation(
    observation: dict[str, Any], *, expected_title: str, expected_content_sha256: str
) -> dict[str, Any]:
    if not isinstance(observation, dict):
        raise TypeError("WeChat editor observation must be an object")
    if observation.get("schema_version") != OBSERVATION_SCHEMA:
        raise ValueError("Unsupported WeChat editor observation schema")
    reject_secrets(observation)
    required = {
        "started_at",
        "saved_at",
        "title",
        "content_sha256",
        "draft_identity",
        "body_images",
        "cover",
        "summary",
        "content_checks",
        "save",
        "refresh_readback",
        "published",
    }
    missing = sorted(required - observation.keys())
    if missing:
        raise ValueError(f"WeChat editor observation is missing: {', '.join(missing)}")
    if observation["published"] is not False:
        raise ValueError("WeChat handoff never publishes")
    if observation["content_sha256"] != expected_content_sha256:
        raise ValueError("WeChat observation does not match the current Content hash")
    if str(observation["title"]).strip() != expected_title.strip():
        raise ValueError("WeChat draft title does not match Content")
    identity = observation["draft_identity"]
    if not isinstance(identity, dict) or not re.fullmatch(
        r"[0-9]+", str(identity.get("appmsgid") or "")
    ):
        raise ValueError("WeChat draft identity requires a stable numeric appmsgid")
    images = observation["body_images"]
    if not isinstance(images, dict) or not isinstance(images.get("items"), list):
        raise TypeError("body_images.items must be an array")
    intended = _nonnegative_int(images.get("intended"), "body_images.intended")
    markers = _nonnegative_int(
        images.get("local_path_markers_remaining"),
        "body_images.local_path_markers_remaining",
    )
    loaded = [item for item in images["items"] if _visible_loaded_image(item)]
    hosted = [item for item in loaded if item.get("host_class") == "wechat"]
    if markers != 0:
        raise ValueError("Local image path markers remain in the saved draft")
    if len(hosted) != intended:
        raise ValueError(
            "Saved draft does not contain every intended WeChat-hosted image"
        )
    if observation.get("cover", {}).get("selected") is not True:
        raise ValueError("WeChat draft cover is not confirmed")
    if observation.get("summary", {}).get("filled") is not True:
        raise ValueError("WeChat draft summary is not filled")
    save = observation["save"]
    if save.get("saved") is not True or save.get("mode") != "draft":
        raise ValueError("WeChat editor did not confirm a draft save")
    refresh = observation["refresh_readback"]
    if not all(
        refresh.get(field) is True
        for field in ("performed", "same_draft", "content_present")
    ):
        raise ValueError("WeChat draft was not verified by refresh readback")
    return json.loads(json.dumps(observation, ensure_ascii=False))


def validate_draft_receipt(
    store: Store, *, job_id: str, receipt_id: str
) -> dict[str, Any]:
    reference = _product_reference(
        store, job_id, "draft_receipt", "receipt_id", receipt_id
    )
    receipt = store.read_json_artifact(job_id, reference["artifact_id"])
    errors: list[str] = []
    if receipt.get("schema_version") != DRAFT_RECEIPT_SCHEMA:
        errors.append("Unsupported draft receipt schema")
    if receipt.get("published") is not False:
        errors.append("Draft receipt must state published=false")
    if receipt.get("job_id") != job_id:
        errors.append("Draft receipt job mismatch")
    try:
        content_reference = _product_reference(
            store,
            job_id,
            "content",
            "content_id",
            str(receipt.get("content_id") or ""),
        )
        if (
            receipt.get("draft_identity", {}).get("content_sha256")
            != content_reference["sha256"]
        ):
            errors.append("Draft receipt Content hash mismatch")
    except (FileNotFoundError, ValueError) as error:
        errors.append(str(error))
    try:
        reject_secrets(receipt)
    except ValueError as error:
        errors.append(str(error))
    return {
        "schema_version": "video-content/draft-receipt-validation-v1",
        "receipt_id": receipt_id,
        "valid": not errors,
        "errors": errors,
        "checked_at": utc_now(),
    }


def _materialize_render_package(
    store: Store, job_id: str, content: dict[str, Any]
) -> Path:
    content_id = str(content["content_id"])
    package = store.job_dir(job_id) / "work" / content_id / "handoff-package"
    package.mkdir(parents=True, exist_ok=True)
    records = 0
    for reference in content.get("artifact_refs") or []:
        relative_value = str(reference.get("metadata", {}).get("relative_path") or "")
        relative = _safe_relative_file(relative_value)
        _, payload = store.read_artifact(job_id, str(reference["artifact_id"]))
        target = (package / Path(*relative.parts)).resolve()
        if package != target and package not in target.parents:
            raise ValueError("Content render path escapes handoff package")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha256_bytes(target.read_bytes()) != reference["sha256"]:
            raise ValueError(
                f"Existing handoff file failed integrity: {relative_value}"
            )
        if not target.exists():
            target.write_bytes(payload)
        records += 1
    if records == 0 or not (package / "article.html").is_file():
        raise ValueError("Validated Content has no reusable WeChat render package")
    return package


def _safe_relative_file(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Unsafe render path: {value!r}")
    return path


def _product_reference(
    store: Store, job_id: str, kind: str, field: str, value: str
) -> dict[str, Any]:
    matches = [
        reference
        for reference in store.list_artifacts(job_id, kind=kind)
        if reference.get("metadata", {}).get(field) == value
    ]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {kind} product for {field}={value}")
    return matches[0]


def _visible_loaded_image(item: Any) -> bool:
    return bool(
        isinstance(item, dict)
        and item.get("visible") is True
        and item.get("complete") is True
        and _positive_number(item.get("natural_width"))
        and _positive_number(item.get("width"))
        and _positive_number(item.get("height"))
    )


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"{label} must be a non-negative integer")
    return value


def _receipt_id(content_id: str, appmsgid: str) -> str:
    digest = hashlib.sha256(f"{content_id}\0{appmsgid}".encode()).hexdigest()
    return f"receipt_{digest[:24]}"
