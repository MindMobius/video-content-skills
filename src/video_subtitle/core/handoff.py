from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .content import get_content_project
from .util import read_json

WECHAT_DRAFT_RECEIPT_VERSION = "video-content/wechat-draft-receipt-v1"


def validate_wechat_draft_receipt(
    receipt_path: Path,
    *,
    project_path: Path | None = None,
) -> dict[str, Any]:
    """Validate durable WeChat draft evidence without touching platform state."""
    receipt_path = receipt_path.expanduser().resolve()
    if not receipt_path.is_file():
        raise FileNotFoundError(f"WeChat draft receipt does not exist: {receipt_path}")
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict):
        raise TypeError("WeChat draft receipt must be a JSON object")

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    required = (
        "schema_version",
        "project_id",
        "deliverable_id",
        "fidelity_audit_id",
        "platform",
        "status",
        "started_at",
        "saved_at",
        "title",
        "appmsgid",
        "body_images",
        "cover",
        "summary",
        "author",
        "originality",
        "content_checks",
        "save",
        "published",
        "publish_actions_performed",
    )
    _require_fields(receipt, required, errors)
    if errors:
        return _validation_result(receipt, errors, warnings, project_path=None)

    _expect_equal(
        receipt,
        "schema_version",
        WECHAT_DRAFT_RECEIPT_VERSION,
        errors,
    )
    _expect_equal(receipt, "platform", "wechat_official_account", errors)
    _expect_equal(receipt, "status", "saved_as_draft", errors)
    _expect_nonempty_string(receipt, "project_id", errors)
    _expect_nonempty_string(receipt, "deliverable_id", errors)
    _expect_nonempty_string(receipt, "fidelity_audit_id", errors)
    _expect_nonempty_string(receipt, "title", errors)
    _expect_nonempty_string(receipt, "appmsgid", errors)
    _validate_timestamps(receipt, errors)
    _validate_body_images(receipt.get("body_images"), errors)
    _validate_cover(receipt.get("cover"), errors)
    _validate_summary(receipt.get("summary"), errors)
    _validate_author(receipt.get("author"), errors)
    _validate_originality(receipt.get("originality"), errors)
    _validate_content_checks(receipt.get("content_checks"), errors, warnings)
    _validate_save(receipt.get("save"), errors)

    if receipt.get("published") is not False:
        errors.append(
            {
                "code": "PUBLISHED_STATE_FORBIDDEN",
                "message": "A draft handoff receipt must record published=false",
            }
        )
    publish_actions = receipt.get("publish_actions_performed")
    if publish_actions != []:
        errors.append(
            {
                "code": "PUBLISH_ACTIONS_FORBIDDEN",
                "message": "A draft handoff must not perform publish actions",
            }
        )

    resolved_project_path = _resolve_project_path(receipt_path, project_path)
    if resolved_project_path is not None:
        _validate_project_binding(receipt, resolved_project_path, errors, warnings)
    else:
        warnings.append(
            {
                "code": "PROJECT_NOT_CHECKED",
                "message": "No content project was found, so artifact IDs were not verified",
            }
        )

    return _validation_result(
        receipt,
        errors,
        warnings,
        project_path=resolved_project_path,
    )


def _validate_timestamps(
    receipt: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    started = _timestamp(receipt.get("started_at"), "started_at", errors)
    saved = _timestamp(receipt.get("saved_at"), "saved_at", errors)
    if started is not None and saved is not None and saved < started:
        errors.append(
            {
                "code": "INVALID_TIME_ORDER",
                "message": "saved_at cannot be earlier than started_at",
            }
        )


def _validate_body_images(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(
            {"code": "INVALID_BODY_IMAGES", "message": "body_images must be an object"}
        )
        return
    fields = (
        "intended",
        "visible_loaded",
        "wechat_hosted",
        "non_wechat_hosted",
        "local_path_markers_remaining",
    )
    if not _require_fields(value, fields, errors, prefix="body_images"):
        return
    counts: dict[str, int] = {}
    for field in fields:
        raw = value[field]
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            errors.append(
                {
                    "code": "INVALID_BODY_IMAGE_COUNT",
                    "message": f"body_images.{field} must be a non-negative integer",
                }
            )
            continue
        counts[field] = raw
    if len(counts) != len(fields):
        return
    if not (counts["intended"] == counts["visible_loaded"] == counts["wechat_hosted"]):
        errors.append(
            {
                "code": "BODY_IMAGE_COUNT_MISMATCH",
                "message": "Intended, visible, and WeChat-hosted image counts must match",
            }
        )
    if counts["non_wechat_hosted"] or counts["local_path_markers_remaining"]:
        errors.append(
            {
                "code": "BODY_IMAGE_IMPORT_INCOMPLETE",
                "message": "No visible local, inline, or non-WeChat image source may remain",
            }
        )


def _validate_cover(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append({"code": "INVALID_COVER", "message": "cover must be an object"})
        return
    if not _require_fields(
        value,
        ("source", "asset", "selected", "crop_confirmed", "wechat_hosted_preview"),
        errors,
        prefix="cover",
    ):
        return
    _expect_nonempty_string(value, "source", errors, prefix="cover")
    _expect_nonempty_string(value, "asset", errors, prefix="cover")
    for field in ("selected", "crop_confirmed", "wechat_hosted_preview"):
        if value.get(field) is not True:
            errors.append(
                {
                    "code": "COVER_NOT_VERIFIED",
                    "message": f"cover.{field} must be true",
                }
            )


def _validate_summary(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(
            {"code": "INVALID_SUMMARY", "message": "summary must be an object"}
        )
        return
    if not _require_fields(value, ("filled", "text"), errors, prefix="summary"):
        return
    if value.get("filled") is not True:
        errors.append(
            {"code": "SUMMARY_NOT_FILLED", "message": "summary.filled must be true"}
        )
    _expect_nonempty_string(value, "text", errors, prefix="summary")


def _validate_author(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append({"code": "INVALID_AUTHOR", "message": "author must be an object"})
        return
    if not _require_fields(value, ("value", "left_blank"), errors, prefix="author"):
        return
    if not isinstance(value.get("value"), str) or not isinstance(
        value.get("left_blank"), bool
    ):
        errors.append(
            {
                "code": "INVALID_AUTHOR_STATE",
                "message": "author.value must be text and author.left_blank must be boolean",
            }
        )
        return
    if value["left_blank"] != (value["value"] == ""):
        errors.append(
            {
                "code": "AUTHOR_STATE_MISMATCH",
                "message": "author.left_blank must match whether author.value is empty",
            }
        )


def _validate_originality(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append(
            {"code": "INVALID_ORIGINALITY", "message": "originality must be an object"}
        )
        return
    if not _require_fields(
        value, ("declared", "visible_state"), errors, prefix="originality"
    ):
        return
    if value.get("declared") is not False:
        errors.append(
            {
                "code": "ORIGINALITY_DECLARATION_FORBIDDEN",
                "message": "This handoff workflow must not declare platform originality",
            }
        )
    _expect_nonempty_string(value, "visible_state", errors, prefix="originality")


def _validate_content_checks(
    value: Any,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            {
                "code": "INVALID_CONTENT_CHECKS",
                "message": "content_checks must be an object",
            }
        )
        return
    required = (
        "source_disclosure_present",
        "ending_present",
        "underline_count",
        "stock_cta_present",
        "speaker_identity_preserved",
    )
    if not _require_fields(value, required, errors, prefix="content_checks"):
        return
    for field in (
        "source_disclosure_present",
        "ending_present",
        "speaker_identity_preserved",
    ):
        if value.get(field) is not True:
            errors.append(
                {
                    "code": "CONTENT_CHECK_FAILED",
                    "message": f"content_checks.{field} must be true",
                }
            )
    if value.get("stock_cta_present") is not False:
        errors.append(
            {
                "code": "STOCK_CTA_PRESENT",
                "message": "The imported article must not add a stock engagement CTA",
            }
        )
    underline_count = value.get("underline_count")
    if not isinstance(underline_count, int) or isinstance(underline_count, bool):
        errors.append(
            {
                "code": "INVALID_UNDERLINE_COUNT",
                "message": "content_checks.underline_count must be an integer",
            }
        )
    elif underline_count > 0:
        warnings.append(
            {
                "code": "UNDERLINE_EMPHASIS_PRESENT",
                "message": "Underline emphasis remains; verify that it is intentional and sparse",
            }
        )


def _validate_save(value: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, dict):
        errors.append({"code": "INVALID_SAVE", "message": "save must be an object"})
        return
    required = (
        "saved",
        "channel",
        "mode",
        "history_record",
        "history_record_persisted",
        "saved_page_read_back",
    )
    if not _require_fields(value, required, errors, prefix="save"):
        return
    if value.get("saved") is not True:
        errors.append({"code": "DRAFT_NOT_SAVED", "message": "save.saved must be true"})
    _expect_nonempty_string(value, "channel", errors, prefix="save")
    _expect_nonempty_string(value, "mode", errors, prefix="save")
    _expect_nonempty_string(value, "history_record", errors, prefix="save")
    if value.get("history_record_persisted") is not True:
        errors.append(
            {
                "code": "SAVE_HISTORY_NOT_PERSISTED",
                "message": "A durable manual-save history entry is required",
            }
        )
    if value.get("saved_page_read_back") is not True:
        errors.append(
            {
                "code": "SAVED_PAGE_NOT_READ_BACK",
                "message": "The saved draft must be read back after saving",
            }
        )


def _validate_project_binding(
    receipt: dict[str, Any],
    project_path: Path,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    try:
        project = get_content_project(project_path)
    except (FileNotFoundError, TypeError, ValueError) as error:
        errors.append({"code": "INVALID_PROJECT", "message": str(error)})
        return
    if receipt.get("project_id") != project.get("project_id"):
        errors.append(
            {"code": "PROJECT_ID_MISMATCH", "message": "Receipt project_id is stale"}
        )
    current = project.get("current") or {}
    if receipt.get("deliverable_id") != current.get("deliverable_id"):
        errors.append(
            {
                "code": "DELIVERABLE_ID_MISMATCH",
                "message": "Receipt does not target the current deliverable",
            }
        )
    if receipt.get("fidelity_audit_id") != current.get("fidelity_audit_id"):
        errors.append(
            {
                "code": "FIDELITY_AUDIT_ID_MISMATCH",
                "message": "Receipt does not target the current fidelity audit",
            }
        )
    integrity = project.get("integrity") or {}
    if not integrity.get("ready_for_delivery"):
        errors.append(
            {
                "code": "PROJECT_NOT_READY_FOR_DELIVERY",
                "message": "The bound content project is not ready for delivery",
            }
        )
    for warning in integrity.get("warnings") or []:
        warnings.append(
            {
                "code": f"PROJECT_{warning.get('code', 'WARNING')}",
                "message": str(warning.get("message") or "Project warning"),
            }
        )


def _resolve_project_path(
    receipt_path: Path,
    requested: Path | None,
) -> Path | None:
    if requested is not None:
        return requested.expanduser().resolve()
    for parent in receipt_path.parents:
        candidate = parent / "project.json"
        if candidate.is_file():
            return candidate.resolve()
    return None


def _require_fields(
    value: dict[str, Any],
    fields: tuple[str, ...],
    errors: list[dict[str, str]],
    *,
    prefix: str = "receipt",
) -> bool:
    missing = [field for field in fields if field not in value]
    if missing:
        errors.append(
            {
                "code": "MISSING_FIELDS",
                "message": f"{prefix} is missing fields: {', '.join(missing)}",
            }
        )
        return False
    return True


def _expect_equal(
    value: dict[str, Any],
    field: str,
    expected: Any,
    errors: list[dict[str, str]],
) -> None:
    if value.get(field) != expected:
        errors.append(
            {
                "code": f"INVALID_{field.upper()}",
                "message": f"{field} must be {expected!r}",
            }
        )


def _expect_nonempty_string(
    value: dict[str, Any],
    field: str,
    errors: list[dict[str, str]],
    *,
    prefix: str = "receipt",
) -> None:
    raw = value.get(field)
    if not isinstance(raw, str) or not raw.strip():
        errors.append(
            {
                "code": "EMPTY_FIELD",
                "message": f"{prefix}.{field} must be non-empty text",
            }
        )


def _timestamp(
    raw: Any,
    field: str,
    errors: list[dict[str, str]],
) -> datetime | None:
    if not isinstance(raw, str):
        errors.append(
            {
                "code": "INVALID_TIMESTAMP",
                "message": f"{field} must be an ISO timestamp",
            }
        )
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        errors.append(
            {
                "code": "INVALID_TIMESTAMP",
                "message": f"{field} must be an ISO timestamp",
            }
        )
        return None
    if parsed.tzinfo is None:
        errors.append(
            {"code": "INVALID_TIMESTAMP", "message": f"{field} must include a timezone"}
        )
        return None
    return parsed


def _validation_result(
    receipt: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    *,
    project_path: Path | None,
) -> dict[str, Any]:
    return {
        "schema_version": "video-content/wechat-draft-receipt-validation-v1",
        "valid": not errors,
        "project_checked": project_path is not None,
        "project_id": receipt.get("project_id"),
        "deliverable_id": receipt.get("deliverable_id"),
        "fidelity_audit_id": receipt.get("fidelity_audit_id"),
        "appmsgid": receipt.get("appmsgid"),
        "errors": errors,
        "warnings": warnings,
    }
