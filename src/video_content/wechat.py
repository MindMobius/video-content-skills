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

OBSERVATION_SCHEMA_V1 = "video-content/wechat-editor-observation-v1"
OBSERVATION_SCHEMA_V2 = "video-content/wechat-editor-observation-v2"
OBSERVATION_SCHEMA_V3 = "video-content/wechat-editor-observation-v3"
OBSERVATION_SCHEMAS = {
    OBSERVATION_SCHEMA_V1,
    OBSERVATION_SCHEMA_V2,
    OBSERVATION_SCHEMA_V3,
}


def wechat_prepare(
    store: Store,
    *,
    job_id: str,
    content_id: str,
    authorized: bool,
    save_draft: bool,
    copy_to_clipboard: bool = False,
    replace_existing_draft: bool = False,
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

    receipts = _receipt_documents(store, job_id)
    if replace_existing_draft:
        active = _active_draft_receipts(store, job_id, receipts)
        if len(active) != 1:
            raise ValueError(
                "Draft replacement requires exactly one current validated receipt"
            )
        previous = active[0]
        if previous.get("content_id") == content_id:
            raise ValueError("Draft replacement requires a revised Content object")
        draft_target = {
            "mode": "replace_existing",
            "appmsgid": previous["draft_identity"]["appmsgid"],
            "supersedes_receipt_id": previous["receipt_id"],
        }
    else:
        if receipts:
            raise ValueError("This job already has a validated WeChat draft receipt")
        draft_target = {"mode": "create_new"}

    package_dir = _materialize_render_package(store, job_id, content)
    transport = prepare_wechat_clipboard(package_dir, copy=copy_to_clipboard)
    content_reference = _product_reference(
        store, job_id, "content", "content_id", content_id
    )
    current = store.get_job(job_id)
    if current["stage"] == "content":
        current = update_job(store, job_id, stage="handoff", status="running")
    required_creation_source = _required_creation_source(store, job_id)
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
        "observation_schema": OBSERVATION_SCHEMA_V3,
        "required_declarations": (
            {"creation_source": required_creation_source}
            if required_creation_source
            else {}
        ),
        "draft_target": draft_target,
        "job": current,
    }


def wechat_bind(
    store: Store,
    *,
    job_id: str,
    content_id: str,
    observation: dict[str, Any],
    supersedes_receipt_id: str | None = None,
) -> dict[str, Any]:
    receipts = _receipt_documents(store, job_id)
    previous: dict[str, Any] | None = None
    if supersedes_receipt_id is None:
        if receipts:
            raise ValueError("This job already has a validated WeChat draft receipt")
    else:
        active = _active_draft_receipts(store, job_id, receipts)
        if len(active) != 1 or active[0].get("receipt_id") != supersedes_receipt_id:
            raise ValueError(
                "Draft revision must supersede the current validated Draft Receipt"
            )
        previous = active[0]
        if previous.get("content_id") == content_id:
            raise ValueError("Draft revision requires a revised Content object")

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
        required_creation_source=_required_creation_source(store, job_id),
    )
    appmsgid = normalized["draft_identity"]["appmsgid"]
    if previous is not None and appmsgid != previous["draft_identity"]["appmsgid"]:
        raise ValueError("Draft revision must read back the same appmsgid")
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
        supersedes_receipt_id=supersedes_receipt_id,
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
    if not (current["stage"] == "completed" and current["status"] == "completed"):
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
    observation: dict[str, Any],
    *,
    expected_title: str,
    expected_content_sha256: str,
    required_creation_source: str | None = None,
) -> dict[str, Any]:
    if not isinstance(observation, dict):
        raise TypeError("WeChat editor observation must be an object")
    schema_version = observation.get("schema_version")
    if schema_version not in OBSERVATION_SCHEMAS:
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
    if intended > 0 and schema_version != OBSERVATION_SCHEMA_V3:
        raise ValueError(
            "Image-bearing WeChat drafts require video-content/wechat-editor-observation-v3"
        )
    require_natural_height = schema_version == OBSERVATION_SCHEMA_V3
    loaded = [
        item
        for item in images["items"]
        if _visible_loaded_image(item, require_natural_height=require_natural_height)
    ]
    hosted = [item for item in loaded if item.get("host_class") == "wechat"]
    if markers != 0:
        raise ValueError("Local image path markers remain in the saved draft")
    if len(hosted) != intended:
        raise ValueError(
            "Saved draft does not contain every intended WeChat-hosted image"
        )
    if require_natural_height and any(
        not _image_aspect_ratio_preserved(item) for item in hosted
    ):
        raise ValueError(
            "Saved draft image aspect ratio does not match the source image"
        )
    if observation.get("cover", {}).get("selected") is not True:
        raise ValueError("WeChat draft cover is not confirmed")
    if observation.get("summary", {}).get("filled") is not True:
        raise ValueError("WeChat draft summary is not filled")

    if required_creation_source and schema_version not in {
        OBSERVATION_SCHEMA_V2,
        OBSERVATION_SCHEMA_V3,
    }:
        raise ValueError(
            "AI creation source requires video-content/wechat-editor-observation-v2 or v3"
        )
    creation_source = observation.get("creation_source")
    creation_source_required = (
        schema_version == OBSERVATION_SCHEMA_V2 or required_creation_source is not None
    )
    if creation_source_required or creation_source is not None:
        if not isinstance(creation_source, dict):
            raise ValueError("WeChat creation source declaration is missing")
        if (
            creation_source.get("declared") is not True
            or creation_source.get("type") != "ai_generated"
            or creation_source.get("read_back") is not True
        ):
            raise ValueError(
                "WeChat creation source must declare and read back AI-generated content"
            )
        if (
            required_creation_source is not None
            and creation_source.get("type") != required_creation_source
        ):
            raise ValueError("WeChat creation source does not match the Profile")

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

    receipts = _receipt_documents(store, job_id)
    successors = [
        item for item in receipts if item.get("supersedes_receipt_id") == receipt_id
    ]
    if successors:
        errors.append("Draft receipt has been superseded by a later revision")
    if len(successors) > 1:
        errors.append("Draft receipt has multiple successor revisions")
    superseded_ids = {
        str(item.get("supersedes_receipt_id"))
        for item in receipts
        if item.get("supersedes_receipt_id")
    }
    active = [
        item
        for item in receipts
        if str(item.get("receipt_id") or "") not in superseded_ids
    ]
    if receipt_id not in superseded_ids and len(active) != 1:
        errors.append("Job does not have exactly one current Draft Receipt")

    predecessor_id = receipt.get("supersedes_receipt_id")
    if predecessor_id:
        predecessors = [
            item for item in receipts if item.get("receipt_id") == predecessor_id
        ]
        if len(predecessors) != 1:
            errors.append("Superseded Draft Receipt does not exist uniquely")
        else:
            predecessor = predecessors[0]
            if predecessor.get("content_id") == receipt.get("content_id"):
                errors.append("Draft revision did not bind revised Content")
            if predecessor.get("draft_identity", {}).get("appmsgid") != receipt.get(
                "draft_identity", {}
            ).get("appmsgid"):
                errors.append("Draft revision changed appmsgid")
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


def _receipt_documents(store: Store, job_id: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for reference in store.list_artifacts(job_id, kind="draft_receipt"):
        documents.append(store.read_json_artifact(job_id, reference["artifact_id"]))
    return documents


def _active_draft_receipts(
    store: Store, job_id: str, receipts: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    selected = list(
        receipts if receipts is not None else _receipt_documents(store, job_id)
    )
    superseded_ids = {
        str(item.get("supersedes_receipt_id"))
        for item in selected
        if item.get("supersedes_receipt_id")
    }
    candidates = [
        item
        for item in selected
        if str(item.get("receipt_id") or "") not in superseded_ids
    ]
    return [
        item
        for item in candidates
        if validate_draft_receipt(
            store, job_id=job_id, receipt_id=str(item.get("receipt_id") or "")
        )["valid"]
        is True
    ]


def _required_creation_source(store: Store, job_id: str) -> str | None:
    job = store.get_job(job_id)
    profile_id = str(job.get("profile_id") or "").strip()
    if not profile_id:
        return None
    value = (
        store.get_profile(profile_id).get("settings", {}).get("wechat_creation_source")
    )
    if value in {None, ""}:
        return None
    if value != "ai_generated":
        raise ValueError(f"Unsupported WeChat creation source requirement: {value!r}")
    return str(value)


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


def _visible_loaded_image(item: Any, *, require_natural_height: bool = False) -> bool:
    return bool(
        isinstance(item, dict)
        and item.get("visible") is True
        and item.get("complete") is True
        and _positive_number(item.get("natural_width"))
        and (not require_natural_height or _positive_number(item.get("natural_height")))
        and _positive_number(item.get("width"))
        and _positive_number(item.get("height"))
    )


def _image_aspect_ratio_preserved(item: dict[str, Any]) -> bool:
    natural_ratio = item["natural_width"] / item["natural_height"]
    rendered_ratio = item["width"] / item["height"]
    return abs(rendered_ratio / natural_ratio - 1) <= 0.01


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"{label} must be a non-negative integer")
    return value


def _receipt_id(content_id: str, appmsgid: str) -> str:
    digest = hashlib.sha256(f"{content_id}\0{appmsgid}".encode()).hexdigest()
    return f"receipt_{digest[:24]}"
