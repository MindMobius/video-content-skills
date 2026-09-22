"""Fail-closed, resumable browser handoff checkpoints inside the existing Job.

The controller observes/clicks visible UI. This module grants a single next action;
restarting a process is never a reason to create another editor or repeat a save.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, get_args

from .locking import exclusive_file_lock
from .store import Store
from .util import read_json, reject_secrets, sha256_file, utc_now, write_json_atomic
from .wechat_docx import build_canonical_clipboard, text_digest

SCHEMA = "video-content/wechat-handoff-checkpoint-v1"
HandoffAction = Literal[
    "attach",
    "begin_import",
    "verify_import",
    "begin_save",
    "saved",
    "readback",
    "recover_saved",
    "reconcile_absent",
    "reconcile_abandoned_import",
    "begin_clipboard",
]
ACTIONS = get_args(HandoffAction)


def _path(store: Store, job_id: str) -> Path:
    return store.job_dir(job_id) / "work" / "wechat-handoff.json"


def read_checkpoint(store: Store, job_id: str) -> dict[str, Any]:
    path = _path(store, job_id)
    if not path.is_file():
        raise ValueError("Run wechat_prepare before any editor mutation")
    return read_json(path)


def initialize_checkpoint(
    store: Store,
    job_id: str,
    *,
    content_id: str,
    content_sha256: str,
    docx: dict[str, Any],
    document: dict[str, Any],
    draft_target: dict[str, Any],
    account_name: str | None,
    legacy_handoff: bool,
    required_creation_source: str | None,
) -> dict[str, Any]:
    path = _path(store, job_id)
    with exclusive_file_lock(path):
        state = read_json(path) if path.is_file() else None
        predecessor = draft_target.get("supersedes_receipt_id")
        if state and state.get("supersedes_receipt_id") == predecessor:
            if (
                state["content_sha256"] != content_sha256
                or state["docx_sha256"] != docx["sha256"]
            ):
                raise ValueError(
                    "Pending handoff belongs to different Content/transport; recover the same draft, do not replace it"
                )
            if account_name and state.get("account_name") not in (None, account_name):
                raise ValueError("Pending handoff account cannot change")
            if account_name and not state.get("account_name"):
                state["account_name"] = account_name
                state["revision"] += 1
                write_json_atomic(path, state)
            return state
        if state and (not predecessor or state.get("phase") != "bound"):
            raise ValueError("An unresolved handoff cannot be replaced")
        state = {
            "schema_version": SCHEMA,
            "job_id": job_id,
            "content_id": content_id,
            "content_sha256": content_sha256,
            "docx_sha256": docx["sha256"],
            "body_sha256": docx["text_sha256"],
            "images": docx["images"],
            "title": document["title"],
            "summary": document["summary"],
            "account_name": account_name,
            "required_creation_source": required_creation_source,
            "supersedes_receipt_id": predecessor,
            "appmsgid": draft_target.get("appmsgid"),
            "phase": "recovery_required"
            if legacy_handoff and not predecessor
            else "prepared",
            "revision": (state["revision"] + 1) if state else 0,
            "import_attempts": 0,
            "started_at": utc_now(),
        }
        reject_secrets(state)
        write_json_atomic(path, state)
        return state


def checkpoint_view(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "next_action": {
            "prepared": "confirm_account_and_attach_visible_editor",
            "recovery_required": "inspect_existing_editor_and_draft_list_do_not_create",
            "target_locked": (
                "begin_clipboard_only_in_confirmed_empty_editor"
                if state.get("import_abandonment_reconciliation")
                else "begin_import_only_in_confirmed_empty_editor"
            ),
            "import_pending": "observe_same_editor_do_not_upload_again",
            "imported": "check_metadata_then_begin_save",
            "save_pending": "find_same_draft_do_not_save_or_create_again",
            "saved": "refresh_same_draft_then_readback",
            "readback_verified": "bind_returned_observation",
            "bound": "complete_do_not_repeat",
        }[state["phase"]],
        "mutation_permitted": False,
    }


def _target(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    *,
    recover_saved: bool = False,
    page_kind: str = "editor",
) -> dict[str, str]:
    target = snapshot.get("target")
    if not isinstance(target, dict) or set(target) != {
        "browser_id",
        "tab_id",
        "document_id",
        "account_name",
    }:
        raise ValueError(
            "Snapshot requires exact browser/tab/document/account identity, without URLs"
        )
    if any(
        not isinstance(v, str) or not v.strip() or len(v) > 160 for v in target.values()
    ):
        raise ValueError("Invalid target identity")
    if not state.get("account_name") or target["account_name"] != state["account_name"]:
        raise ValueError("Expected account must be confirmed before handoff")
    if snapshot.get("page_kind") != page_kind or snapshot.get("editor_type") != "77":
        raise ValueError("Target is not the expected visible type=77 editor")
    if snapshot.get("ready") is not True:
        raise ValueError("Ambiguous editor snapshot")
    previous = state.get("target")
    if (
        previous
        and not recover_saved
        and any(
            target[k] != previous[k] for k in ("browser_id", "tab_id", "account_name")
        )
    ):
        raise ValueError("Browser/tab/account changed; recover the pinned target")
    return target


def _fresh(snapshot: dict[str, Any], state: dict[str, Any]) -> None:
    # Epoch milliseconds are emitted by the live adapter; stale files cannot reserve actions.
    observed = snapshot.get("observed_at")
    try:
        age = datetime.now(timezone.utc).timestamp() * 1000 - float(observed)
    except (TypeError, ValueError):
        raise ValueError("Snapshot needs a fresh observed_at epoch timestamp") from None
    if not 0 <= age <= 60000:
        raise ValueError("Stale/future browser snapshot; observe the same target again")
    sid = snapshot.get("snapshot_id")
    if (
        not isinstance(sid, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", sid)
        or sid == state.get("last_snapshot_id")
    ):
        raise ValueError("Snapshot must be freshly collected, not reused")


def _body(snapshot: dict[str, Any], state: dict[str, Any]) -> None:
    if snapshot.get("import_busy") is not False or snapshot.get("dialogs") != []:
        raise ValueError(
            "Import still busy or a dialog requires inspection; a dialog is not success"
        )
    text = snapshot.get("body_text")
    if not isinstance(text, str) or text_digest(text) != state["body_sha256"]:
        raise ValueError(
            "Full body does not match canonical Content; old/partial text is not import success"
        )
    images = snapshot.get("images")
    if not isinstance(images, list) or len(images) != len(state["images"]):
        raise ValueError("Imported image count differs from canonical Content")
    if snapshot.get("local_path_markers_remaining") != 0:
        raise ValueError("Local image markers remain")
    for actual, expected in zip(images, state["images"]):
        if (
            actual.get("visible") is not True
            or actual.get("complete") is not True
            or actual.get("host_class") != "wechat"
        ):
            raise ValueError("Body image not visibly loaded on WeChat")
        sizes = [
            actual.get(k)
            for k in ("natural_width", "natural_height", "width", "height")
        ]
        if any(
            not isinstance(v, (int, float))
            or isinstance(v, bool)
            or not 0 < v < 1000000
            for v in sizes
        ):
            raise ValueError("Invalid body image dimensions")
        nw, nh, w, h = sizes
        if (
            abs((nw / nh) / (expected["pixel_width"] / expected["pixel_height"]) - 1)
            > 0.01
            or abs((w / h) / (nw / nh) - 1) > 0.01
        ):
            raise ValueError("Body image aspect ratio changed")


def _metadata(snapshot: dict[str, Any], state: dict[str, Any]) -> None:
    if (
        snapshot.get("title") != state["title"]
        or snapshot.get("summary") != state["summary"]
    ):
        raise ValueError("Title/summary differ from approved Content")
    if snapshot.get("author") != "" or snapshot.get("original_declared") is not False:
        raise ValueError("Author must remain blank and originality undeclared")
    cover = snapshot.get("cover", {})
    sizes = [cover.get("rendered_width"), cover.get("rendered_height")]
    if (
        cover.get("selected") is not True
        or cover.get("crop_confirmed") is not True
        or any(
            not isinstance(v, (int, float))
            or isinstance(v, bool)
            or not 0 < v < 1000000
            for v in sizes
        )
    ):
        raise ValueError("Cover must be explicitly selected, cropped and visible")
    if state.get("required_creation_source") == "ai_generated":
        creation = snapshot.get("creation_source", {})
        if (
            creation.get("selected_count") != 1
            or creation.get("label") != "内容由AI生成"
        ):
            raise ValueError(
                "Exactly one visible AI creation-source control must be selected"
            )


def advance_checkpoint(
    store: Store,
    job_id: str,
    content_id: str,
    *,
    action: HandoffAction,
    expected_revision: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise TypeError("expected_revision must be an integer from wechat_prepare")
    if action not in ACTIONS:
        raise ValueError("Unsupported handoff action")
    reject_secrets(snapshot)
    path = _path(store, job_id)
    with exclusive_file_lock(path):
        state = read_checkpoint(store, job_id)
        if state["content_id"] != content_id or state["revision"] != expected_revision:
            raise ValueError(
                "Stale handoff revision/Content; reread wechat_prepare, do not repeat the action"
            )
        if state["phase"] == "bound":
            raise ValueError("Draft already bound; no further mutation")
        _fresh(snapshot, state)
        if action in ("reconcile_absent", "reconcile_abandoned_import"):
            abandoned = action == "reconcile_abandoned_import"
            if abandoned:
                lost = snapshot.get("abandoned_editor", {})
                pinned = state.get("target") or {}
                if (
                    state["phase"] != "import_pending"
                    or not pinned
                    or state.get("appmsgid")
                    or state.get("clipboard_attempts", 0)
                    or state.get("import_abandonment_reconciliation")
                ):
                    raise ValueError(
                        "Only an unsaved DOCX import can be reconciled as abandoned"
                    )
                _fresh(lost, state)
                if lost.get("kind") == "tab_absent":
                    # Browser/session restart: the pinned tab no longer exists, so its
                    # unsaved editor content is gone with it. The draft-list check
                    # below still has to prove nothing was saved before the loss.
                    tab_ids = lost.get("tab_ids")
                    if (
                        not isinstance(tab_ids, list)
                        or not all(isinstance(t, str) and t for t in tab_ids)
                        or pinned["tab_id"] in tab_ids
                        or lost.get("browser_id") != pinned["browser_id"]
                        or lost.get("snapshot_id") == snapshot["snapshot_id"]
                    ):
                        raise ValueError(
                            "Abandoned import needs a fresh tab enumeration proving the pinned tab is gone"
                        )
                else:
                    previous = lost.get("target", {})
                    if (
                        lost.get("page_kind") != "blank"
                        or lost.get("body_text") is not None
                        or lost.get("images") != []
                        or lost.get("appmsgid")
                        or lost.get("dialogs") != []
                        or lost.get("snapshot_id") == snapshot["snapshot_id"]
                        or any(
                            previous.get(k) != pinned.get(k)
                            for k in ("browser_id", "tab_id")
                        )
                        or not previous.get("document_id")
                        or previous["document_id"] == pinned["document_id"]
                    ):
                        raise ValueError(
                            "Abandoned import needs a fresh blank-page observation of the exact pinned tab"
                        )
                target = _target(
                    snapshot, state, recover_saved=True, page_kind="draft_list"
                )
                if target["browser_id"] != pinned["browser_id"]:
                    raise ValueError(
                        "Draft absence must be checked in the same browser/account"
                    )
            else:
                if (
                    state["phase"] != "recovery_required"
                    or state.get("target")
                    or state.get("appmsgid")
                ):
                    raise ValueError(
                        "Absence reconciliation is only for an unbound legacy handoff"
                    )
                _target(snapshot, state, page_kind="draft_list")
            entries = snapshot.get("entries")
            if (
                snapshot.get("loaded_all") is not True
                or snapshot.get("unfiltered") is not True
                or not isinstance(entries, list)
                or snapshot.get("total") != len(entries)
            ):
                raise ValueError("A complete unfiltered visible draft list is required")
            since = datetime.fromisoformat(
                store.get_job(job_id)["created_at"].replace("Z", "+00:00")
            ).timestamp()
            seen = set()
            for entry in entries:
                ident = str(entry.get("appmsgid", ""))
                created = entry.get("created_at_epoch")
                if (
                    not re.fullmatch(r"[0-9]+", ident)
                    or ident in seen
                    or not isinstance(created, (int, float))
                    or isinstance(created, bool)
                    or not 0 < created < since
                    or entry.get("title") == state["title"]
                    or entry.get("title_visible") is not True
                ):
                    raise ValueError(
                        "Possible saved draft or incomplete list evidence; inspect instead of restarting"
                    )
                seen.add(ident)
            reconciliation = {
                "observed_at": snapshot["observed_at"],
                "target": snapshot["target"],
                "draft_ids": sorted(seen),
                "no_drafts_since_job_creation": True,
            }
            if abandoned:
                reconciliation.update(
                    previous_target=state.pop("target"),
                    lost_observation={
                        "kind": lost.get("kind", "blank_page"),
                        "observed_at": lost["observed_at"],
                    },
                )
                state["import_abandonment_reconciliation"] = reconciliation
            else:
                state["legacy_absence_reconciliation"] = reconciliation
            state["phase"] = "prepared"
            state["last_snapshot_id"] = snapshot["snapshot_id"]
            state["revision"] += 1
            write_json_atomic(path, state)
            return checkpoint_view(state)
        if action == "recover_saved" and not state.get("appmsgid"):
            raise ValueError("Cannot move an unsaved/unknown draft to another tab")
        clipboard_delivery_info = None
        target = _target(snapshot, state, recover_saved=action == "recover_saved")
        phase = state["phase"]
        appmsgid = snapshot.get("appmsgid")
        if appmsgid and not re.fullmatch(r"[0-9]+", str(appmsgid)):
            raise ValueError("Invalid draft identity")
        if state.get("appmsgid") and str(appmsgid or "") != state["appmsgid"]:
            raise ValueError("Must retain the same appmsgid")
        if (
            action in ("begin_import", "begin_clipboard", "verify_import", "begin_save")
            and state.get("target")
            and target["document_id"] != state["target"]["document_id"]
        ):
            raise ValueError("Editor document changed; reconcile the same draft first")
        permit = None
        if action == "attach":
            if phase not in ("prepared", "recovery_required"):
                raise ValueError(
                    "Target already pinned; resume instead of attaching a different editor"
                )
            if phase == "recovery_required":
                _body(snapshot, state)
                _metadata(snapshot, state)
                # Recovery proves a matching article, never authorizes another import.
                state["phase"] = "imported"
            else:
                if not state.get("appmsgid") and (
                    appmsgid
                    or snapshot.get("body_text", "").strip()
                    or snapshot.get("images")
                ):
                    raise ValueError(
                        "New handoff requires a verified empty, unsaved editor"
                    )
                state["phase"] = "target_locked"
            state["target"] = target
        elif action == "begin_import":
            if state.get("import_abandonment_reconciliation"):
                raise ValueError(
                    "Recovered abandoned import must use the single guarded fallback, not repeat DOCX"
                )
            retry = (
                phase == "import_pending"
                and isinstance(snapshot.get("import_error"), str)
                and bool(snapshot["import_error"].strip())
            )
            if phase != "target_locked" and not retry:
                raise ValueError(
                    "Import already reserved or uncertain; observe before retrying"
                )
            if (
                snapshot.get("body_text") != ""
                or snapshot.get("images") != []
                or snapshot.get("import_busy") is not False
            ):
                raise ValueError(
                    "Never import over existing or uncertain editor content"
                )
            if not retry and snapshot.get("dialogs") != []:
                raise ValueError("Resolve the visible dialog before reserving import")
            if state["import_attempts"] >= 2:
                raise ValueError(
                    "Import retry budget exhausted; diagnose without deleting content/images"
                )
            state["import_attempts"] += 1
            state["phase"] = "import_pending"
            permit = "upload_exact_docx_once"
        elif action == "begin_clipboard":
            explicit_failure = (
                phase == "import_pending"
                and state.get("import_attempts") == 2
                and isinstance(snapshot.get("import_error"), str)
                and bool(snapshot["import_error"].strip())
            )
            recovered_absence = (
                phase == "target_locked"
                and bool(state.get("import_abandonment_reconciliation"))
                and snapshot.get("dialogs") == []
            )
            prior_attempts = state.get("clipboard_attempts", 0)
            redeliver = (
                prior_attempts == 1
                and state.get("transport") == "canonical_clipboard"
                and state.get("clipboard_delivery") != "delivered"
                and not state.get("clipboard_redelivered")
            )
            if (
                not (explicit_failure or recovered_absence)
                or (prior_attempts != 0 and not redeliver)
                or state.get("appmsgid")
                or snapshot.get("body_text") != ""
                or snapshot.get("images") != []
                or snapshot.get("import_busy") is not False
            ):
                raise ValueError(
                    "Clipboard fallback needs two explicit failed imports or verified abandoned-import recovery in an empty unsaved editor"
                )
            from .content import get_content

            clipboard = build_canonical_clipboard(
                store, job_id, get_content(store, job_id, content_id)
            )
            if clipboard["text_sha256"] != state["body_sha256"] or clipboard[
                "image_ids"
            ] != [i["artifact_id"] for i in state["images"]]:
                raise ValueError("Fallback transport differs from canonical manuscript")
            if redeliver and clipboard["sha256"] != state["clipboard_sha256"]:
                raise ValueError(
                    "Fallback payload changed; recover the same manuscript, never a variant"
                )
            from .wechat_adapter import copy_html_to_windows_clipboard

            delivery = "delivered"
            delivery_error = None
            try:
                copy_html_to_windows_clipboard(
                    clipboard["html"], clipboard["plain_text"]
                )
            except OSError as exc:
                # Some hosts (win32 ERROR_ACCESS_DENIED from a restricted
                # session) cannot write the interactive clipboard. The permit
                # still reserves the single paste; an interactive-session
                # runner must deliver the same payload, and verify_import
                # remains the actual proof.
                delivery = "permit_issued"
                delivery_error = str(exc)
            state["clipboard_attempts"] = 1
            state["transport"] = "canonical_clipboard"
            state["clipboard_sha256"] = clipboard["sha256"]
            state["clipboard_delivery"] = delivery
            if delivery_error:
                state["clipboard_delivery_error"] = delivery_error
            if redeliver:
                state["clipboard_redelivered"] = True
            clipboard_delivery_info = {
                "copied": delivery == "delivered",
                "delivery_error": delivery_error,
            }
            permit = "paste_canonical_clipboard_once"
        elif action == "verify_import":
            if phase not in ("import_pending", "target_locked"):
                raise ValueError("No pending import to verify")
            if phase == "target_locked":
                if state.get("appmsgid"):
                    raise ValueError(
                        "New article must use the reserved canonical import"
                    )
                if state.get("transport") != "canonical_clipboard":
                    raise ValueError(
                        "New article must use the reserved canonical import"
                    )
                if state.get("clipboard_attempts", 0) != 1:
                    raise ValueError(
                        "Clipboard fallback must reserve exactly one paste before verification"
                    )
            _body(snapshot, state)
            state["phase"] = "imported"
        elif action == "begin_save":
            if phase != "imported":
                raise ValueError(
                    "Save already reserved or content not verified; do not click again"
                )
            _body(snapshot, state)
            _metadata(snapshot, state)
            state["phase"] = "save_pending"
            state["pre_save_document_id"] = target["document_id"]
            permit = "save_draft_once"
        elif action == "saved":
            if (
                phase not in ("save_pending", "recovery_required", "imported")
                or not appmsgid
            ):
                raise ValueError("Observe a stable same-draft appmsgid before readback")
            _body(snapshot, state)
            _metadata(snapshot, state)
            state["appmsgid"] = str(appmsgid)
            state["target"] = target
            state["saved_document_id"] = target["document_id"]
            state["saved_at"] = utc_now()
            state["phase"] = "saved"
        elif action == "recover_saved":
            _body(snapshot, state)
            _metadata(snapshot, state)
            if snapshot.get("draft_list_appmsgid") != state["appmsgid"]:
                raise ValueError(
                    "Recovery requires the known same appmsgid in the draft list"
                )
            state["target"] = target
            state["saved_document_id"] = target["document_id"]
            state.setdefault("saved_at", utc_now())
            state["phase"] = "saved"
        elif action == "readback":
            if phase != "saved" or target["document_id"] == state["saved_document_id"]:
                raise ValueError(
                    "Readback requires refresh/reopen of the same draft, not the pre-save DOM"
                )
            _body(snapshot, state)
            _metadata(snapshot, state)
            cover = snapshot["cover"]
            if (
                any(
                    cover.get(k) is not True
                    for k in (
                        "editor_visible_after_refresh",
                        "list_thumbnail_read_back",
                        "persistent_media_present",
                        "crop_data_present",
                    )
                )
                or snapshot.get("draft_list_appmsgid") != state["appmsgid"]
            ):
                raise ValueError(
                    "Same-draft list and refreshed cover evidence required"
                )
            observation = {
                "schema_version": "video-content/wechat-editor-observation-v4",
                "started_at": state["started_at"],
                "saved_at": state["saved_at"],
                "title": state["title"],
                "content_sha256": state["content_sha256"],
                "draft_identity": {"appmsgid": state["appmsgid"]},
                "body_images": {
                    "intended": len(state["images"]),
                    "items": [
                        {
                            k: image[k]
                            for k in (
                                "visible",
                                "complete",
                                "natural_width",
                                "natural_height",
                                "width",
                                "height",
                                "host_class",
                            )
                        }
                        for image in snapshot["images"]
                    ],
                    "local_path_markers_remaining": 0,
                },
                "cover": {
                    k: cover[k]
                    for k in (
                        "selected",
                        "crop_confirmed",
                        "editor_visible_after_refresh",
                        "rendered_width",
                        "rendered_height",
                        "list_thumbnail_read_back",
                        "persistent_media_present",
                        "crop_data_present",
                    )
                },
                "summary": {"filled": True, "text": state["summary"]},
                "content_checks": {
                    "source_disclosure_present": True,
                    "opening_present": True,
                    "middle_present": True,
                    "ending_present": True,
                    "stock_cta_present": False,
                },
                "save": {"saved": True, "mode": "draft", "history_read_back": True},
                "refresh_readback": {
                    "performed": True,
                    "same_draft": True,
                    "content_present": True,
                },
                "published": False,
            }
            if state.get("required_creation_source") == "ai_generated":
                observation["creation_source"] = {
                    "declared": True,
                    "type": "ai_generated",
                    "read_back": True,
                }
            state["observation"] = observation
            state["phase"] = "readback_verified"
        if permit == "upload_exact_docx_once":
            docx_path = (
                store.job_dir(job_id)
                / "work"
                / content_id
                / "handoff-package"
                / "document-import"
                / "article-import.docx"
            )
            if (
                not docx_path.is_file()
                or sha256_file(docx_path) != state["docx_sha256"]
            ):
                raise ValueError(
                    "Canonical DOCX bytes changed; never upload an unverified variant"
                )
        state["last_snapshot_id"] = snapshot["snapshot_id"]
        state["revision"] += 1
        reject_secrets(state)
        write_json_atomic(path, state)
    result = checkpoint_view(state)
    if permit == "paste_canonical_clipboard_once":
        info = clipboard_delivery_info
        result["clipboard_copied"] = info["copied"]
        if not info["copied"]:
            result["clipboard_delivery"] = "agent_delivery_required"
            result["clipboard_delivery_error"] = info["delivery_error"]
        result["clipboard_sha256"] = state["clipboard_sha256"]
    if permit:
        result["mutation_permitted"] = True
        result["permitted_action"] = permit
        if permit == "upload_exact_docx_once":
            result["upload_path"] = str(docx_path)
    return result


def require_verified_checkpoint(
    store: Store, job_id: str, content_id: str, observation: dict[str, Any]
) -> dict[str, Any]:
    state = read_checkpoint(store, job_id)
    if (
        state["content_id"] != content_id
        or state["phase"] != "readback_verified"
        or state.get("observation") != observation
    ):
        raise ValueError(
            "Receipt requires the exact observation returned by wechat_step readback; handwritten success flags are not accepted"
        )
    return state


def mark_bound(store: Store, job_id: str, receipt_id: str) -> None:
    path = _path(store, job_id)
    with exclusive_file_lock(path):
        state = read_checkpoint(store, job_id)
        state["phase"] = "bound"
        state["receipt_id"] = receipt_id
        state["revision"] += 1
        write_json_atomic(path, state)
