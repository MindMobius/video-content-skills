"""Validate a durable video-content/draft-receipt-v1 artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_content.store import Store
from video_content.wechat import validate_draft_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--receipt-id", required=True)
    args = parser.parse_args()
    result = validate_draft_receipt(
        Store(args.home), job_id=args.job_id, receipt_id=args.receipt_id
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
