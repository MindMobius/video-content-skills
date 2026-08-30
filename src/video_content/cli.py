from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import api
from .config import CONFIG_ENVIRONMENT, apply_configuration
from .util import json_for_stdout

COMMAND_SURFACE = {
    "system": {"setup", "configure", "doctor"},
    "source": {"inspect"},
    "evidence": {"start"},
    "job": {"get", "list", "update", "artifacts", "read-artifact"},
    "media": {"extract-frame"},
    "content": {"save-transcript", "save", "validate"},
    "watch-later": {"scan"},
    "wechat": {"prepare", "bind"},
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-content",
        description="Agent-native video evidence and content runtime",
    )
    parser.add_argument("--config")
    parser.add_argument("--home")
    groups = parser.add_subparsers(dest="group", required=True)

    system = groups.add_parser("system")
    system_actions = system.add_subparsers(dest="action", required=True)
    for name in ("setup", "doctor"):
        command = system_actions.add_parser(name)
        command.add_argument("--capability", action="append", default=[])
        command.add_argument("--deep", action="store_true")
    configure = system_actions.add_parser("configure")
    configure.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
    configure.add_argument("--clear", action="append", default=[])

    source = groups.add_parser("source")
    source_actions = source.add_subparsers(dest="action", required=True)
    inspect = source_actions.add_parser("inspect")
    inspect.add_argument("url")
    inspect.add_argument("--page", type=int)

    evidence = groups.add_parser("evidence")
    evidence_actions = evidence.add_subparsers(dest="action", required=True)
    start = evidence_actions.add_parser("start")
    start.add_argument("url")
    start.add_argument("--page", type=int)
    start.add_argument("--run-id")
    start.add_argument("--profile-id")
    start.add_argument("--language", default="ai-zh")
    start.add_argument("--ocr-backend", default="auto")
    start.add_argument("--asr-backend", default="none")
    start.add_argument("--video-path")
    start.add_argument("--no-download", action="store_true")
    start.add_argument("--collect-all-sources", action="store_true")
    start.add_argument(
        "--media-execution", choices=("auto", "serial", "parallel"), default="auto"
    )
    start.add_argument(
        "--hard-subtitle-visual-decision",
        choices=("not_assessed", "continuous", "not_continuous", "uncertain"),
        default="not_assessed",
    )
    start.add_argument("--visual-assessment-json", type=Path)

    job = groups.add_parser("job")
    job_actions = job.add_subparsers(dest="action", required=True)
    get = job_actions.add_parser("get")
    get.add_argument("job_id")
    listing = job_actions.add_parser("list")
    listing.add_argument("--run-id")
    listing.add_argument("--status")
    listing.add_argument("--profile-id")
    update = job_actions.add_parser("update")
    update.add_argument("job_id")
    update.add_argument("--stage")
    update.add_argument("--status")
    update.add_argument("--error-json", type=Path)
    update.add_argument("--retry-at")
    update.add_argument("--increment-attempts", action="store_true")
    artifacts = job_actions.add_parser("artifacts")
    artifacts.add_argument("job_id")
    artifacts.add_argument("--kind")
    read_artifact = job_actions.add_parser("read-artifact")
    read_artifact.add_argument("job_id")
    read_artifact.add_argument("artifact_id")
    read_artifact.add_argument("--base64", action="store_true")

    media = groups.add_parser("media")
    media_actions = media.add_subparsers(dest="action", required=True)
    extract_frame = media_actions.add_parser("extract-frame")
    extract_frame.add_argument("job_id")
    extract_frame.add_argument("timestamp_ms", type=int)
    extract_frame.add_argument("--selection-reason", required=True)

    content = groups.add_parser("content")
    content_actions = content.add_subparsers(dest="action", required=True)
    transcript = content_actions.add_parser("save-transcript")
    transcript.add_argument("job_id")
    transcript.add_argument("input", type=Path)
    save = content_actions.add_parser("save")
    save.add_argument("job_id")
    save.add_argument("input", type=Path)
    validate = content_actions.add_parser("validate")
    validate.add_argument("job_id")
    validate.add_argument("content_id")

    watch = groups.add_parser("watch-later")
    watch_actions = watch.add_subparsers(dest="action", required=True)
    scan = watch_actions.add_parser("scan")
    scan.add_argument("profile_id")
    scan.add_argument("--account-profile-alias")
    scan.add_argument("--carrier", default="wechat_article")
    scan.add_argument("--limit", type=int)
    scan.add_argument("--baseline-if-empty", action="store_true")

    wechat = groups.add_parser("wechat")
    wechat_actions = wechat.add_subparsers(dest="action", required=True)
    prepare = wechat_actions.add_parser("prepare")
    prepare.add_argument("job_id")
    prepare.add_argument("content_id")
    prepare.add_argument("--authorized", action="store_true")
    prepare.add_argument("--save-draft", action="store_true")
    prepare.add_argument("--copy-to-clipboard", action="store_true")
    prepare.add_argument("--replace-existing-draft", action="store_true")
    bind = wechat_actions.add_parser("bind")
    bind.add_argument("job_id")
    bind.add_argument("content_id")
    bind.add_argument("observation", type=Path)
    bind.add_argument("--supersedes-receipt-id")
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    common = {"home": args.home}
    if args.group == "system":
        if args.action == "setup":
            return api.system_setup(args.capability or None, config_path=args.config)
        if args.action == "doctor":
            return api.system_doctor(
                args.capability or None, deep=args.deep, config_path=args.config
            )
        return api.system_configure(
            _assignments(args.set), clear=args.clear, config_path=args.config
        )
    if args.group == "source":
        return api.source_inspect(args.url, args.page, config_path=args.config)
    if args.group == "evidence":
        return api.evidence_start(
            args.url,
            **common,
            page=args.page,
            run_id=args.run_id,
            profile_id=args.profile_id,
            language=args.language,
            ocr_backend=args.ocr_backend,
            asr_backend=args.asr_backend,
            video_path=args.video_path,
            download_if_needed=not args.no_download,
            collect_all_sources=args.collect_all_sources,
            media_execution=args.media_execution,
            hard_subtitle_visual_decision=args.hard_subtitle_visual_decision,
            visual_assessment=(
                _json_file(args.visual_assessment_json)
                if args.visual_assessment_json
                else None
            ),
            config_path=args.config,
        )
    if args.group == "job":
        if args.action == "get":
            return api.job_get(args.job_id, **common)
        if args.action == "list":
            return api.job_list(
                **common,
                run_id=args.run_id,
                status=args.status,
                profile_id=args.profile_id,
            )
        if args.action == "update":
            return api.job_update(
                args.job_id,
                **common,
                stage=args.stage,
                status=args.status,
                error=_json_file(args.error_json) if args.error_json else None,
                retry_at=args.retry_at,
                increment_attempts=args.increment_attempts,
            )
        if args.action == "artifacts":
            return api.artifact_list(args.job_id, **common, kind=args.kind)
        return api.artifact_read(
            args.job_id, args.artifact_id, **common, text=not args.base64
        )
    if args.group == "media":
        return api.source_frame_extract(
            args.job_id,
            args.timestamp_ms,
            args.selection_reason,
            **common,
            config_path=args.config,
        )
    if args.group == "content":
        if args.action == "validate":
            return api.content_validate(args.job_id, args.content_id, **common)
        document = _json_file(args.input)
        if args.action == "save-transcript":
            return api.transcript_save(args.job_id, home=args.home, **document)
        return api.content_save(args.job_id, home=args.home, **document)
    if args.group == "watch-later":
        return api.watch_later_scan(
            args.profile_id,
            **common,
            account_profile_alias=args.account_profile_alias,
            carrier=args.carrier,
            limit=args.limit,
            baseline_if_empty=args.baseline_if_empty,
            config_path=args.config,
        )
    if args.action == "prepare":
        return api.wechat_prepare(
            args.job_id,
            args.content_id,
            **common,
            authorized=args.authorized,
            save_draft=args.save_draft,
            copy_to_clipboard=args.copy_to_clipboard,
            replace_existing_draft=args.replace_existing_draft,
        )
    return api.wechat_bind(
        args.job_id,
        args.content_id,
        _json_file(args.observation),
        **common,
        supersedes_receipt_id=args.supersedes_receipt_id,
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # Every CLI command uses the same discovered project configuration.
        # An explicit --config still wins; otherwise config.py selects the
        # repository-local .video-content/config.json when present.
        apply_configuration(args.config)
        result = dispatch(args)
        output = {"ok": True, "result": result}
        code = 0
    except (
        FileNotFoundError,
        OSError,
        PermissionError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        output = {
            "ok": False,
            "error": {"type": type(error).__name__, "message": str(error)},
        }
        code = 1
    print(json_for_stdout(output))
    raise SystemExit(code)


def _assignments(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        field, separator, item = value.partition("=")
        if not separator or field not in CONFIG_ENVIRONMENT or not item:
            raise ValueError(f"Invalid configuration assignment: {value!r}")
        result[field] = item
    return result


def _json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON input must be an object: {path}")
    return value


if __name__ == "__main__":
    main()
