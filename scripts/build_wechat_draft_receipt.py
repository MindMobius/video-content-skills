"""Build and validate a no-secret WeChat Draft Receipt in a Video Content Store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_content.store import Store
from video_content.wechat import wechat_bind


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observation", type=Path)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--content-id", required=True)
    args = parser.parse_args()
    try:
        observation = json.loads(args.observation.read_text(encoding="utf-8"))
        result = wechat_bind(
            Store(args.home),
            job_id=args.job_id,
            content_id=args.content_id,
            observation=observation,
        )
        output = {
            "schema_version": "video-content/draft-receipt-build-v1",
            "ok": True,
            **result,
        }
    except (
        OSError,
        PermissionError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        output = {
            "schema_version": "video-content/draft-receipt-build-v1",
            "ok": False,
            "error": str(error),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 1)


if __name__ == "__main__":
    main()
