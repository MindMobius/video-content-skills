"""Simulated controller for regression tests only; never touches a real browser."""

from __future__ import annotations

import time
import uuid
from copy import deepcopy

from video_content.content import get_content
from video_content.wechat import wechat_prepare
from video_content.wechat_docx import manuscript_parts
from video_content.wechat_handoff import advance_checkpoint, read_checkpoint


def snapshot_for(
    store,
    job_id,
    content_id,
    *,
    empty=False,
    appmsgid=None,
    document_id="document-before",
    **changes,
):
    state = read_checkpoint(store, job_id)
    content = get_content(store, job_id, content_id)
    text = "\n".join(
        str(x["text"]) for x in manuscript_parts(content["document"]) if "text" in x
    )
    images = [
        {
            "visible": True,
            "complete": True,
            "natural_width": x["pixel_width"],
            "natural_height": x["pixel_height"],
            "width": x["pixel_width"] / 2,
            "height": x["pixel_height"] / 2,
            "host_class": "wechat",
        }
        for x in state["images"]
    ]
    snap = {
        "snapshot_id": uuid.uuid4().hex,
        "observed_at": time.time() * 1000,
        "target": {
            "browser_id": "simulated",
            "tab_id": "test-tab",
            "document_id": document_id,
            "account_name": state.get("account_name") or "测试账号",
        },
        "page_kind": "editor",
        "editor_type": "77",
        "ready": True,
        "body_text": "" if empty else text,
        "images": [] if empty else images,
        "import_busy": False,
        "dialogs": [],
        "local_path_markers_remaining": 0,
        "appmsgid": appmsgid,
        "title": state["title"],
        "summary": state["summary"],
        "author": "",
        "original_declared": False,
        "cover": {
            "selected": True,
            "crop_confirmed": True,
            "rendered_width": 235,
            "rendered_height": 100,
            "editor_visible_after_refresh": True,
            "list_thumbnail_read_back": True,
            "persistent_media_present": True,
            "crop_data_present": True,
        },
        "creation_source": {"selected_count": 1, "label": "内容由AI生成"},
        "draft_list_appmsgid": appmsgid,
    }
    snap.update(deepcopy(changes))
    return snap


def step(store, job_id, content_id, action, snapshot):
    state = read_checkpoint(store, job_id)
    return advance_checkpoint(
        store,
        job_id,
        content_id,
        action=action,
        expected_revision=state["revision"],
        snapshot=snapshot,
    )


def verified_observation(store, job_id, content_id, appmsgid="100000721"):
    state = read_checkpoint(store, job_id)
    wechat_prepare(
        store,
        job_id=job_id,
        content_id=content_id,
        authorized=True,
        save_draft=True,
        account_name="测试账号",
        replace_existing_draft=bool(state.get("supersedes_receipt_id")),
    )
    state = read_checkpoint(store, job_id)
    previous = state.get("appmsgid")
    legacy = state["phase"] == "recovery_required"
    step(
        store,
        job_id,
        content_id,
        "attach",
        snapshot_for(store, job_id, content_id, empty=not legacy, appmsgid=previous),
    )
    if not legacy:
        step(
            store,
            job_id,
            content_id,
            "begin_import",
            snapshot_for(store, job_id, content_id, empty=True, appmsgid=previous),
        )
        step(
            store,
            job_id,
            content_id,
            "verify_import",
            snapshot_for(store, job_id, content_id, appmsgid=previous),
        )
    step(
        store,
        job_id,
        content_id,
        "begin_save",
        snapshot_for(store, job_id, content_id, appmsgid=previous),
    )
    step(
        store,
        job_id,
        content_id,
        "saved",
        snapshot_for(store, job_id, content_id, appmsgid=appmsgid),
    )
    result = step(
        store,
        job_id,
        content_id,
        "readback",
        snapshot_for(
            store,
            job_id,
            content_id,
            appmsgid=appmsgid,
            document_id="document-after-refresh",
        ),
    )
    return result["observation"]
