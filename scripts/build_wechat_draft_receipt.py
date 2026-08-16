"""Build and validate a no-secret WeChat draft receipt from browser observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_subtitle.wechat_adapter import write_and_validate_wechat_draft_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observation", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = write_and_validate_wechat_draft_receipt(
            args.project,
            args.observation,
            args.output,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        result = {
            "schema_version": "video-content/wechat-draft-receipt-build-v1",
            "ok": False,
            "error": str(error),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
