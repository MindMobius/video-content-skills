"""Validate a durable WeChat draft handoff receipt without platform access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_subtitle.core.handoff import validate_wechat_draft_receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a video-content/wechat-draft-receipt-v1 document",
    )
    parser.add_argument("receipt", type=Path)
    parser.add_argument(
        "--project",
        type=Path,
        help="Content project.json; auto-discovered from receipt parents when omitted",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = validate_wechat_draft_receipt(
        args.receipt,
        project_path=args.project,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
