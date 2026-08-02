import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("example_name", "schema_name"),
    [
        ("content-map.json", "content-map.schema.json"),
        ("media-plan.json", "media-plan.schema.json"),
        ("fidelity-audit.json", "fidelity-audit.schema.json"),
    ],
)
def test_video_to_content_examples_match_published_schemas(
    example_name: str,
    schema_name: str,
) -> None:
    example = json.loads(
        (ROOT / "skills" / "video-to-content" / "examples" / example_name).read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))

    jsonschema.validate(example, schema)
