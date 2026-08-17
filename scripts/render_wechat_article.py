"""Render and validate the first-party restrained WeChat article package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_wechat_package import validate_package
from video_content.wechat_renderer import render_wechat_package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manuscript", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        rendered = render_wechat_package(args.manuscript, args.output)
        validation = validate_package(args.output)
        result = {
            "schema_version": "video-content/wechat-render-validation-v1",
            "ok": bool(rendered["ok"] and validation["valid"]),
            "render": rendered,
            "validation": validation,
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        result = {
            "schema_version": "video-content/wechat-render-validation-v1",
            "ok": False,
            "error": str(error),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
