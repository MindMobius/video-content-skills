from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_wechat_service import _observation, _ready_content
from wechat_handoff_helpers import snapshot_for, step, verified_observation

from video_content.wechat import wechat_bind, wechat_prepare
from video_content.wechat_handoff import advance_checkpoint, read_checkpoint


def prepared(tmp_path):
    store, job, content = _ready_content(tmp_path)
    result = wechat_prepare(
        store,
        job_id=job,
        content_id=content,
        authorized=True,
        save_draft=True,
        account_name="测试账号",
    )
    return store, job, content, result


def attached(tmp_path):
    store, job, content, result = prepared(tmp_path)
    step(store, job, content, "attach", snapshot_for(store, job, content, empty=True))
    return store, job, content, result


def importing(tmp_path):
    store, job, content, result = attached(tmp_path)
    step(
        store,
        job,
        content,
        "begin_import",
        snapshot_for(store, job, content, empty=True),
    )
    return store, job, content, result


@pytest.mark.parametrize(
    "change",
    [
        {"body_text": "上次文档的正文" * 200},
        {"body_text": "正文证据"},
        {"dialogs": ["导入中"]},
        {"dialogs": ["文档导入出错，请重试"]},
        {"import_busy": True},
        {"images": []},
        {"local_path_markers_remaining": 1},
    ],
)
def test_old_or_partial_body_and_any_dialog_are_not_import_success(tmp_path, change):
    store, job, content, _ = importing(tmp_path)
    before = read_checkpoint(store, job)
    with pytest.raises(ValueError):
        step(
            store,
            job,
            content,
            "verify_import",
            snapshot_for(store, job, content, **change),
        )
    assert read_checkpoint(store, job) == before


def test_restart_resumes_pending_import_and_cannot_upload_again(tmp_path):
    store, job, content, _ = importing(tmp_path)
    resumed = wechat_prepare(
        store, job_id=job, content_id=content, authorized=True, save_draft=True
    )
    assert resumed["draft_target"]["mode"] == "resume_pending"
    assert resumed["checkpoint"]["phase"] == "import_pending"
    assert resumed["checkpoint"]["mutation_permitted"] is False
    with pytest.raises(ValueError, match="already reserved"):
        step(
            store,
            job,
            content,
            "begin_import",
            snapshot_for(store, job, content, empty=True),
        )
    step(store, job, content, "verify_import", snapshot_for(store, job, content))


@pytest.mark.parametrize(
    "field,value",
    [
        ("browser_id", "other"),
        ("tab_id", "other"),
        ("account_name", "wrong"),
        ("document_id", "navigated-away"),
    ],
)
def test_identity_drift_blocks_mutation(tmp_path, field, value):
    store, job, content, _ = attached(tmp_path)
    snap = snapshot_for(store, job, content, empty=True)
    snap["target"][field] = value
    with pytest.raises(ValueError):
        step(store, job, content, "begin_import", snap)
    assert read_checkpoint(store, job)["phase"] == "target_locked"


def test_no_confirmed_account_cannot_attach(tmp_path):
    store, job, content = _ready_content(tmp_path)
    wechat_prepare(
        store, job_id=job, content_id=content, authorized=True, save_draft=True
    )
    with pytest.raises(ValueError, match="account"):
        step(
            store, job, content, "attach", snapshot_for(store, job, content, empty=True)
        )


def test_stale_snapshot_and_replayed_revision_rejected(tmp_path):
    store, job, content, _ = attached(tmp_path)
    snap = snapshot_for(
        store, job, content, empty=True, observed_at=(time.time() - 120) * 1000
    )
    with pytest.raises(ValueError, match="Stale"):
        step(store, job, content, "begin_import", snap)
    revision = read_checkpoint(store, job)["revision"]
    snap = snapshot_for(store, job, content, empty=True)
    grant = advance_checkpoint(
        store,
        job,
        content,
        action="begin_import",
        expected_revision=revision,
        snapshot=snap,
    )
    assert grant["permitted_action"] == "upload_exact_docx_once"
    assert Path(grant["upload_path"]).is_file()
    with pytest.raises(ValueError, match="Stale"):
        advance_checkpoint(
            store,
            job,
            content,
            action="begin_import",
            expected_revision=revision,
            snapshot=snap,
        )


def test_concurrent_agents_cannot_reserve_the_same_upload_twice(tmp_path):
    store, job, content, _ = attached(tmp_path)
    revision = read_checkpoint(store, job)["revision"]

    def reserve(_):
        try:
            return advance_checkpoint(
                store,
                job,
                content,
                action="begin_import",
                expected_revision=revision,
                snapshot=snapshot_for(store, job, content, empty=True),
            )["mutation_permitted"]
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [False, True]


def test_changed_docx_cannot_be_uploaded(tmp_path):
    store, job, content, result = attached(tmp_path)
    Path(result["document_import"]["path"]).write_bytes(b"a test variant")
    with pytest.raises(ValueError, match="DOCX bytes changed"):
        step(
            store,
            job,
            content,
            "begin_import",
            snapshot_for(store, job, content, empty=True),
        )


def test_retry_requires_explicit_failure_empty_body_and_has_a_budget(tmp_path):
    store, job, content, _ = importing(tmp_path)
    # A real error does not authorize overwriting any body that is already present.
    with pytest.raises(ValueError, match="existing or uncertain"):
        step(
            store,
            job,
            content,
            "begin_import",
            snapshot_for(store, job, content, import_error="导入失败"),
        )
    step(
        store,
        job,
        content,
        "begin_import",
        snapshot_for(store, job, content, empty=True, import_error="导入失败"),
    )
    with pytest.raises(ValueError, match="budget exhausted"):
        step(
            store,
            job,
            content,
            "begin_import",
            snapshot_for(store, job, content, empty=True, import_error="导入失败"),
        )


def test_save_timeout_cannot_repeat_save_and_refresh_is_required(tmp_path):
    store, job, content, _ = importing(tmp_path)
    step(store, job, content, "verify_import", snapshot_for(store, job, content))
    result = step(store, job, content, "begin_save", snapshot_for(store, job, content))
    assert result["permitted_action"] == "save_draft_once"
    with pytest.raises(ValueError, match="Save already reserved"):
        step(store, job, content, "begin_save", snapshot_for(store, job, content))
    with pytest.raises(ValueError, match="appmsgid"):
        step(store, job, content, "saved", snapshot_for(store, job, content))
    step(
        store,
        job,
        content,
        "saved",
        snapshot_for(store, job, content, appmsgid="10001"),
    )
    with pytest.raises(ValueError, match="refresh/reopen"):
        step(
            store,
            job,
            content,
            "readback",
            snapshot_for(store, job, content, appmsgid="10001"),
        )
    with pytest.raises(ValueError, match="same appmsgid"):
        step(
            store,
            job,
            content,
            "readback",
            snapshot_for(
                store, job, content, appmsgid="10002", document_id="refreshed"
            ),
        )
    result = step(
        store,
        job,
        content,
        "readback",
        snapshot_for(store, job, content, appmsgid="10001", document_id="refreshed"),
    )
    bound = wechat_bind(
        store, job_id=job, content_id=content, observation=result["observation"]
    )
    assert bound["validation"]["valid"] is True
    assert read_checkpoint(store, job)["phase"] == "bound"


def test_handwritten_success_cannot_bypass_gate(tmp_path):
    store, job, content, result = prepared(tmp_path)
    with pytest.raises(ValueError, match="exact observation"):
        wechat_bind(
            store,
            job_id=job,
            content_id=content,
            observation=_observation(result["content_sha256"]),
        )
    obs = verified_observation(store, job, content)
    changed = copy.deepcopy(obs)
    changed["saved_at"] = "2026-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="exact observation"):
        wechat_bind(store, job_id=job, content_id=content, observation=changed)
    assert not store.list_artifacts(job, kind="draft_receipt")


def test_legacy_handoff_never_assumes_safe_to_create(tmp_path):
    store, job, content = _ready_content(tmp_path)
    old = store.get_job(job)
    old["stage"] = "handoff"
    store.write_job(old)
    result = wechat_prepare(
        store,
        job_id=job,
        content_id=content,
        authorized=True,
        save_draft=True,
        account_name="测试账号",
    )
    assert result["checkpoint"]["phase"] == "recovery_required"
    assert result["draft_target"]["mode"] == "resume_pending"
    with pytest.raises(ValueError):
        step(
            store, job, content, "attach", snapshot_for(store, job, content, empty=True)
        )


def test_checkpoint_contains_no_body_text_urls_or_secrets(tmp_path):
    store, job, content, _ = prepared(tmp_path)
    verified_observation(store, job, content)
    payload = (store.job_dir(job) / "work" / "wechat-handoff.json").read_text(
        encoding="utf8"
    )
    assert "https://" not in payload
    assert "body_text" not in payload
    assert "token" not in payload.lower()
    assert json.loads(payload)["schema_version"].endswith("checkpoint-v1")


def test_known_saved_draft_can_be_recovered_in_a_new_controlled_tab(tmp_path):
    store, job, content, _ = importing(tmp_path)
    with pytest.raises(ValueError, match="unsaved/unknown"):
        step(
            store,
            job,
            content,
            "recover_saved",
            snapshot_for(store, job, content, appmsgid="10001"),
        )
    step(store, job, content, "verify_import", snapshot_for(store, job, content))
    step(store, job, content, "begin_save", snapshot_for(store, job, content))
    step(
        store,
        job,
        content,
        "saved",
        snapshot_for(store, job, content, appmsgid="10001"),
    )
    snap = snapshot_for(store, job, content, appmsgid="10001", document_id="reopened")
    snap["target"]["tab_id"] = "new-controlled-tab"
    recovered = step(store, job, content, "recover_saved", snap)
    assert recovered["mutation_permitted"] is False
    assert recovered["phase"] == "saved"
    snap = snapshot_for(
        store, job, content, appmsgid="10001", document_id="refreshed-new-tab"
    )
    snap["target"]["tab_id"] = "new-controlled-tab"
    assert step(store, job, content, "readback", snap)["phase"] == "readback_verified"


def test_secrets_and_unverified_clipboard_fallback_are_rejected(tmp_path):
    store, job, content, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match="clipboard fallback"):
        wechat_prepare(
            store,
            job_id=job,
            content_id=content,
            authorized=True,
            save_draft=True,
            copy_to_clipboard=True,
        )
    snap = snapshot_for(store, job, content, empty=True)
    snap["token"] = "must-not-persist"
    with pytest.raises(ValueError, match="secret-like"):
        step(store, job, content, "attach", snap)


def test_job_update_cannot_claim_wechat_completion_without_receipt(tmp_path):
    from video_content.jobs import update_job

    store, job, _, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match="validated Draft Receipt"):
        update_job(store, job, stage="completed", status="completed")
    assert store.get_job(job)["stage"] == "handoff"


def test_profile_account_is_reusable_and_cannot_be_silently_overridden(tmp_path):
    store, job, content = _ready_content(tmp_path)
    store.save_profile(
        {
            "profile_id": "account-profile",
            "carrier": "wechat_article",
            "source": {},
            "settings": {"wechat_account_name": "正确账号"},
        }
    )
    current = store.get_job(job)
    current["profile_id"] = "account-profile"
    store.write_job(current)
    result = wechat_prepare(
        store, job_id=job, content_id=content, authorized=True, save_draft=True
    )
    assert result["checkpoint"]["account_name"] == "正确账号"
    with pytest.raises(ValueError, match="authorized Profile"):
        wechat_prepare(
            store,
            job_id=job,
            content_id=content,
            authorized=True,
            save_draft=True,
            account_name="错误账号",
        )


def legacy_prepared(tmp_path):
    store, job, content = _ready_content(tmp_path)
    old = store.get_job(job)
    old["stage"] = "handoff"
    store.write_job(old)
    wechat_prepare(
        store,
        job_id=job,
        content_id=content,
        authorized=True,
        save_draft=True,
        account_name="测试账号",
    )
    return store, job, content


def absence_snapshot(store, job, content):
    snap = snapshot_for(store, job, content)
    snap.update(
        page_kind="draft_list",
        loaded_all=True,
        unfiltered=True,
        total=1,
        entries=[
            {
                "appmsgid": "100000001",
                "title": "历史草稿",
                "created_at_epoch": 1700000000,
                "title_visible": True,
            }
        ],
    )
    return snap


def test_legacy_absence_requires_full_fresh_list_and_preserves_recovery_evidence(
    tmp_path,
):
    store, job, content = legacy_prepared(tmp_path)
    result = step(
        store, job, content, "reconcile_absent", absence_snapshot(store, job, content)
    )
    assert result["phase"] == "prepared"
    assert result["mutation_permitted"] is False
    assert result["legacy_absence_reconciliation"]["draft_ids"] == ["100000001"]
    step(store, job, content, "attach", snapshot_for(store, job, content, empty=True))


@pytest.mark.parametrize(
    "change",
    [
        {"loaded_all": False},
        {"unfiltered": False},
        {"total": 2},
        {"page_kind": "other"},
        {
            "entries": [
                {
                    "appmsgid": "100000001",
                    "title": "未决稿",
                    "created_at_epoch": time.time() + 3600,
                    "title_visible": True,
                }
            ]
        },
        {
            "entries": [
                {
                    "appmsgid": "100000001",
                    "title": "历史草稿",
                    "created_at_epoch": 1700000000,
                    "title_visible": False,
                }
            ]
        },
    ],
)
def test_incomplete_or_possible_current_draft_does_not_reset_legacy(tmp_path, change):
    store, job, content = legacy_prepared(tmp_path)
    before = read_checkpoint(store, job)
    snap = absence_snapshot(store, job, content)
    snap.update(change)
    with pytest.raises(ValueError):
        step(store, job, content, "reconcile_absent", snap)
    assert read_checkpoint(store, job) == before


def test_absence_cannot_reset_an_inflight_import(tmp_path):
    store, job, content, _ = importing(tmp_path)
    with pytest.raises(ValueError, match="legacy"):
        step(
            store,
            job,
            content,
            "reconcile_absent",
            absence_snapshot(store, job, content),
        )


def test_explicit_clipboard_fallback_retains_content_and_is_reserved_once(
    tmp_path, monkeypatch
):
    store, job, content, _ = importing(tmp_path)
    failed = lambda: snapshot_for(
        store,
        job,
        content,
        empty=True,
        import_error="文档导入出错",
        import_busy=False,
        dialogs=["文档导入出错"],
    )
    step(store, job, content, "begin_import", failed())
    copied = []
    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard",
        lambda html, text: copied.append((html, text)),
    )
    result = step(store, job, content, "begin_clipboard", failed())
    assert result["mutation_permitted"] is True
    assert result["permitted_action"] == "paste_canonical_clipboard_once"
    assert result["clipboard_copied"] is True
    assert len(copied) == 1
    assert copied[0][0].count("<img ") == len(result["images"])
    with pytest.raises(ValueError, match="failed imports"):
        step(store, job, content, "begin_clipboard", failed())


def test_clipboard_win32_failure_keeps_permit_and_allows_one_redelivery(
    tmp_path, monkeypatch
):
    store, job, content, _ = importing(tmp_path)
    failed = lambda: snapshot_for(
        store,
        job,
        content,
        empty=True,
        import_error="文档导入出错",
        import_busy=False,
        dialogs=["文档导入出错"],
    )
    step(store, job, content, "begin_import", failed())

    def deny(*_):
        raise OSError("Could not open the Windows clipboard")

    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard", deny
    )
    result = step(store, job, content, "begin_clipboard", failed())
    assert result["mutation_permitted"] is True
    assert result["clipboard_copied"] is False
    assert result["clipboard_delivery"] == "agent_delivery_required"
    assert result["clipboard_sha256"]
    checkpoint = read_checkpoint(store, job)
    assert checkpoint["clipboard_attempts"] == 1
    assert checkpoint["clipboard_delivery"] == "permit_issued"

    # One identical redelivery is allowed after a delivery failure.
    result = step(store, job, content, "begin_clipboard", failed())
    assert result["mutation_permitted"] is True
    assert result["clipboard_sha256"] == checkpoint["clipboard_sha256"]
    assert read_checkpoint(store, job)["clipboard_redelivered"] is True
    with pytest.raises(ValueError, match="failed imports|empty unsaved editor"):
        step(store, job, content, "begin_clipboard", failed())


def test_clipboard_redelivery_rejects_changed_manuscript(tmp_path, monkeypatch):
    store, job, content, _ = importing(tmp_path)
    failed = lambda: snapshot_for(
        store,
        job,
        content,
        empty=True,
        import_error="文档导入出错",
        import_busy=False,
        dialogs=["文档导入出错"],
    )
    step(store, job, content, "begin_import", failed())

    def deny(*_):
        raise OSError("denied")

    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard", deny
    )
    step(store, job, content, "begin_clipboard", failed())
    checkpoint_path = store.job_dir(job) / "work" / "wechat-handoff.json"
    state = read_checkpoint(store, job)
    state["clipboard_sha256"] = "0" * 64
    checkpoint_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="payload changed"):
        step(store, job, content, "begin_clipboard", failed())


def test_clipboard_route_verifies_paste_from_target_locked(tmp_path, monkeypatch):
    store, job, content, _ = importing(tmp_path)
    failed = lambda: snapshot_for(
        store,
        job,
        content,
        empty=True,
        import_error="文档导入出错",
        import_busy=False,
        dialogs=["文档导入出错"],
    )
    step(store, job, content, "begin_import", failed())
    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard", lambda *_: None
    )
    step(store, job, content, "begin_clipboard", failed())
    result = step(
        store, job, content, "verify_import", snapshot_for(store, job, content)
    )
    assert result["phase"] == "imported"
    assert result["transport"] == "canonical_clipboard"


@pytest.mark.parametrize(
    "change", [{"import_busy": True}, {"body_text": "已有正文"}, {"import_error": ""}]
)
def test_uncertain_import_never_gets_clipboard_fallback(tmp_path, monkeypatch, change):
    store, job, content, _ = importing(tmp_path)
    failed = snapshot_for(
        store,
        job,
        content,
        empty=True,
        import_error="文档导入出错",
        import_busy=False,
        dialogs=["文档导入出错"],
    )
    step(store, job, content, "begin_import", failed)
    snap = snapshot_for(
        store,
        job,
        content,
        empty=True,
        import_error="文档导入出错",
        import_busy=False,
        dialogs=["文档导入出错"],
    )
    snap.update(change)
    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard",
        lambda *_: pytest.fail("must not touch clipboard"),
    )
    with pytest.raises(ValueError):
        step(store, job, content, "begin_clipboard", snap)


def lost_import_snapshot(store, job, content):
    outer = absence_snapshot(store, job, content)
    outer["target"]["tab_id"] = "separate-list-tab"
    lost = snapshot_for(store, job, content)
    lost["target"]["document_id"] = "new-blank-document"
    lost["target"]["account_name"] = ""
    lost.update(
        page_kind="blank",
        ready=False,
        editor_type=None,
        body_text=None,
        images=[],
        dialogs=[],
        appmsgid=None,
    )
    outer["abandoned_editor"] = lost
    return outer


def test_verified_lost_import_can_recover_once_without_resetting_budget(
    tmp_path, monkeypatch
):
    store, job, content, _ = importing(tmp_path)
    before = read_checkpoint(store, job)
    result = step(
        store,
        job,
        content,
        "reconcile_abandoned_import",
        lost_import_snapshot(store, job, content),
    )
    assert result["phase"] == "prepared"
    assert result["mutation_permitted"] is False
    assert result["import_attempts"] == before["import_attempts"]
    assert result["docx_sha256"] == before["docx_sha256"]
    assert (
        result["import_abandonment_reconciliation"]["previous_target"]
        == before["target"]
    )
    snap = snapshot_for(store, job, content, empty=True)
    snap["target"]["tab_id"] = "recovered-editor"
    step(store, job, content, "attach", snap)
    with pytest.raises(ValueError):
        step(
            store,
            job,
            content,
            "reconcile_abandoned_import",
            lost_import_snapshot(store, job, content),
        )
    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard", lambda *_: None
    )
    snap = snapshot_for(store, job, content, empty=True)
    snap["target"]["tab_id"] = "recovered-editor"
    result = step(store, job, content, "begin_clipboard", snap)
    assert result["permitted_action"] == "paste_canonical_clipboard_once"
    assert result["clipboard_attempts"] == 1
    prepared = wechat_prepare(
        store, job_id=job, content_id=content, authorized=True, save_draft=True
    )
    assert prepared["transport"] == "canonical_clipboard"


def tab_absent_snapshot(store, job, content, tab_ids=("unrelated-tab",)):
    outer = absence_snapshot(store, job, content)
    outer["target"]["tab_id"] = "separate-list-tab"
    outer["abandoned_editor"] = {
        "kind": "tab_absent",
        "snapshot_id": "lost" + str(time.time_ns()),
        "observed_at": time.time() * 1000,
        "browser_id": read_checkpoint(store, job)["target"]["browser_id"],
        "tab_ids": list(tab_ids),
    }
    return outer


def test_lost_pinned_tab_can_recover_after_browser_restart(tmp_path, monkeypatch):
    store, job, content, _ = importing(tmp_path)
    before = read_checkpoint(store, job)
    result = step(
        store,
        job,
        content,
        "reconcile_abandoned_import",
        tab_absent_snapshot(store, job, content),
    )
    assert result["phase"] == "prepared"
    assert result["import_attempts"] == before["import_attempts"]
    assert (
        result["import_abandonment_reconciliation"]["lost_observation"]["kind"]
        == "tab_absent"
    )
    snap = snapshot_for(store, job, content, empty=True)
    snap["target"]["tab_id"] = "new-session-tab"
    step(store, job, content, "attach", snap)
    monkeypatch.setattr(
        "video_content.wechat_adapter.copy_html_to_windows_clipboard", lambda *_: None
    )
    snap = snapshot_for(store, job, content, empty=True)
    snap["target"]["tab_id"] = "new-session-tab"
    result = step(store, job, content, "begin_clipboard", snap)
    assert result["permitted_action"] == "paste_canonical_clipboard_once"


@pytest.mark.parametrize(
    "change", ["pinned_still_listed", "wrong_browser", "missing_list", "stale"]
)
def test_tab_absent_recovery_rejects_uncertain_evidence(tmp_path, change):
    store, job, content, _ = importing(tmp_path)
    pinned = read_checkpoint(store, job)["target"]
    snap = tab_absent_snapshot(store, job, content)
    lost = snap["abandoned_editor"]
    if change == "pinned_still_listed":
        lost["tab_ids"] = [pinned["tab_id"]]
    elif change == "wrong_browser":
        lost["browser_id"] = "chrome:other-profile"
    elif change == "missing_list":
        lost["tab_ids"] = "not-a-list"
    else:
        lost["observed_at"] -= 120000
    before = read_checkpoint(store, job)
    with pytest.raises(ValueError):
        step(store, job, content, "reconcile_abandoned_import", snap)
    assert read_checkpoint(store, job) == before


@pytest.mark.parametrize(
    "change",
    [
        "old_document",
        "wrong_tab",
        "login",
        "existing_body",
        "stale_blank",
        "incomplete_list",
        "new_draft",
        "save_pending",
        "clipboard_pending",
    ],
)
def test_lost_import_recovery_rejects_uncertain_or_saved_results(tmp_path, change):
    store, job, content, _ = importing(tmp_path)
    snap = lost_import_snapshot(store, job, content)
    lost = snap["abandoned_editor"]
    if change == "old_document":
        lost["target"]["document_id"] = read_checkpoint(store, job)["target"][
            "document_id"
        ]
    elif change == "wrong_tab":
        lost["target"]["tab_id"] = "unrelated"
    elif change == "login":
        lost["page_kind"] = "other"
    elif change == "existing_body":
        lost["body_text"] = "尚有正文"
    elif change == "stale_blank":
        lost["observed_at"] -= 120000
    elif change == "incomplete_list":
        snap["loaded_all"] = False
    elif change == "new_draft":
        snap["entries"][0]["created_at_epoch"] = time.time() + 1000
    else:
        cp = store.job_dir(job) / "work" / "wechat-handoff.json"
        state = read_checkpoint(store, job)
        if change == "save_pending":
            state["phase"] = "save_pending"
        else:
            state["clipboard_attempts"] = 1
        cp.write_text(json.dumps(state), encoding="utf-8")
    before = read_checkpoint(store, job)
    with pytest.raises(ValueError):
        step(store, job, content, "reconcile_abandoned_import", snap)
    assert read_checkpoint(store, job) == before
