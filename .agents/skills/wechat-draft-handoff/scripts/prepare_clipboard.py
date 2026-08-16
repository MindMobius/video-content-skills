"""Validate a WeChat package and place transient rich HTML on the clipboard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_wechat_package import validate_package
from video_subtitle.wechat_adapter import prepare_wechat_clipboard


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Write the transient payload to the Windows clipboard",
    )
    args = parser.parse_args()
    validation = validate_package(args.package, clean_html=args.html)
    if not validation["valid"]:
        result = {
            "schema_version": "video-content/wechat-clipboard-transport-v1",
            "ok": False,
            "copied": False,
            "validation": validation,
        }
    else:
        try:
            result = prepare_wechat_clipboard(
                args.package,
                clean_html=args.html,
                copy=args.copy,
            )
            result["validation"] = validation
        except (OSError, TypeError, ValueError) as error:
            result = {
                "schema_version": "video-content/wechat-clipboard-transport-v1",
                "ok": False,
                "copied": False,
                "error": str(error),
                "validation": validation,
            }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
