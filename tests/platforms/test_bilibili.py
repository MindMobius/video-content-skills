import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from video_subtitle.platforms.bilibili import (
    OpenCliClient,
    OpenCliError,
    OpenCliSettings,
    bilibili_auth_ready,
)


def test_doctor_discovery_can_report_stale_opencli_path(tmp_path: Path) -> None:
    missing = tmp_path / "OpenCLI" / "dist" / "src" / "main.js"

    settings = OpenCliSettings.discover(
        opencli=str(missing),
        allow_missing=True,
    )

    assert settings.command[-1] == str(missing)
    assert OpenCliClient(settings).is_command_available() is False


def _client() -> OpenCliClient:
    return OpenCliClient(
        OpenCliSettings(command=("opencli",), profile="bridge-profile")
    )


@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_video_rows_become_metadata(mock_run) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            '[{"field":"bvid","value":"BV1abc"},{"field":"title","value":"测试视频"}]'
        ),
        stderr="",
    )
    result = _client().video("https://www.bilibili.com/video/BV1abc")
    assert result == {"bvid": "BV1abc", "title": "测试视频"}
    command = mock_run.call_args.args[0]
    assert command[:3] == ["opencli", "--profile", "bridge-profile"]
    assert command[-2:] == ["-f", "json"]


@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_video_repairs_gb18030_text_decoded_as_latin1(mock_run) -> None:
    mojibake_title = "AI 味的克星竟是 1986 年的飞机维修手册".encode("gb18030").decode(
        "latin-1"
    )
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            '[{"field":"bvid","value":"BV1abc"},'
            f'{{"field":"title","value":"{mojibake_title}"}}]'
        ),
        stderr="",
    )

    result = _client().video("https://www.bilibili.com/video/BV1abc")

    assert result["title"] == "AI 味的克星竟是 1986 年的飞机维修手册"


@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_video_preserves_valid_unicode_and_latin_text(mock_run) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            '[{"field":"bvid","value":"BV1abc"},'
            '{"field":"title","value":"测试 Café Vusal"}]'
        ),
        stderr="",
    )

    result = _client().video("https://www.bilibili.com/video/BV1abc")

    assert result["title"] == "测试 Café Vusal"


@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_yaml_error_envelope_is_structured(mock_run) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=66,
        stdout="",
        stderr=(
            "ok: false\n"
            "error:\n"
            "  code: EMPTY_RESULT\n"
            "  message: bilibili subtitle returned no data\n"
            "  help: no platform subtitle\n"
            "  exitCode: 66\n"
        ),
    )
    with pytest.raises(OpenCliError) as caught:
        _client().subtitles("BV1abc")
    assert caught.value.code == "EMPTY_RESULT"
    assert caught.value.exit_code == 66
    assert caught.value.help_text == "no platform subtitle"


@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_log_prefix_before_json_is_accepted(mock_run) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='debug line\n[{"index":1,"from":"0.00s","to":"1.00s","content":"ok"}]',
        stderr="",
    )
    result = _client().subtitles("BV1abc")
    assert result[0]["content"] == "ok"


def test_auth_ready_requires_a_logged_in_bilibili_row() -> None:
    assert bilibili_auth_ready(
        [{"site": "bilibili", "status": "logged_in", "logged_in": True}]
    )
    assert not bilibili_auth_ready(
        [{"site": "bilibili", "status": "logged_out", "logged_in": False}]
    )
