from __future__ import annotations

import importlib
import json
from pathlib import Path

import jsonschema
import pytest


def test_distribution_metadata_and_module() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))
    assert 'name = "video-content-skills"' in project
    assert 'version = "1.0.0"' in project
    assert package["name"] == "video-content-skills"
    assert package["version"] == "1.0.0"
    assert package["private"] is True
    module = importlib.import_module("video_content")
    assert module.__version__ == "1.0.0"


def test_six_core_schema_ids_are_stable() -> None:
    expected = {
        "video-content/profile-v1",
        "video-content/job-v1",
        "video-content/evidence-v1",
        "video-content/transcript-v1",
        "video-content/content-v1",
        "video-content/draft-receipt-v1",
    }
    paths = [
        Path("schemas/profile.schema.json"),
        Path("schemas/job.schema.json"),
        Path("schemas/evidence.schema.json"),
        Path("schemas/transcript.schema.json"),
        Path("schemas/content.schema.json"),
        Path("schemas/draft-receipt.schema.json"),
    ]
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert {schema["$id"] for schema in schemas} == expected
    for schema in schemas:
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False


def test_draft_receipt_can_never_be_published() -> None:
    schema = json.loads(
        Path("schemas/draft-receipt.schema.json").read_text(encoding="utf-8")
    )
    document = {
        "schema_version": "video-content/draft-receipt-v1",
        "receipt_id": "receipt_1",
        "job_id": "job_1",
        "content_id": "content_1",
        "platform": "wechat_official_account",
        "draft_identity": {},
        "observation": {},
        "published": True,
        "saved_at": "2026-08-17T00:00:00Z",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)
