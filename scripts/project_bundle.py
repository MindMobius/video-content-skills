"""Export, verify, or import a portable video-content project bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_subtitle.core.portable import (
    export_content_bundle,
    import_content_bundle,
    verify_content_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export_parser = commands.add_parser("export")
    export_parser.add_argument("--project", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--include", type=Path, action="append", default=[])
    export_parser.add_argument("--agent", default="not_recorded")
    export_parser.add_argument("--model", default="not_recorded")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("bundle", type=Path)
    import_parser = commands.add_parser("import")
    import_parser.add_argument("bundle", type=Path)
    import_parser.add_argument("--destination", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "export":
            result = export_content_bundle(
                args.project,
                args.output,
                include=args.include,
                agent_name=args.agent,
                model_name=args.model,
            )
        elif args.command == "verify":
            result = verify_content_bundle(args.bundle)
            result["ok"] = result["valid"]
        else:
            result = import_content_bundle(args.bundle, args.destination)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        result = {
            "schema_version": "video-content/portable-bundle-command-v1",
            "ok": False,
            "error": str(error),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
