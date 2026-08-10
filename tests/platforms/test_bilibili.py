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
    assert mock_run.call_args.kwargs["env"]["OPENCLI_BROWSER_COMMAND_TIMEOUT"] == "180"


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


@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_download_uses_persistent_cache_and_reports_actual_file_size(
    mock_run,
    tmp_path: Path,
) -> None:
    def download_once(command, **kwargs):
        output_dir = Path(command[command.index("--output") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "video.mp4").write_bytes(b"x" * 4096)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='[{"status":"success","size":"238.0 KB"}]',
            stderr="",
        )

    mock_run.side_effect = download_once
    client = _client()
    cache_dir = tmp_path / "cache"

    first_path, first = client.download(
        "https://www.bilibili.com/video/BV1abc",
        tmp_path / "job-one",
        quality="1080p",
        page=1,
        cache_dir=cache_dir,
        cache_key="BV1abc",
    )
    second_path, second = client.download(
        "https://www.bilibili.com/video/BV1abc",
        tmp_path / "job-two",
        quality="1080p",
        page=1,
        cache_dir=cache_dir,
        cache_key="BV1abc",
    )

    assert mock_run.call_count == 1
    assert first_path == second_path
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["attempt_count"] == 0
    assert first["actual_bytes"] == 4096
    assert first["actual_mib"] == round(4096 / (1024 * 1024), 3)


@patch("video_subtitle.platforms.bilibili.time.sleep")
@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_download_retries_transient_timeout(
    mock_run,
    mock_sleep,
    tmp_path: Path,
) -> None:
    def run(command, **kwargs):
        if mock_run.call_count == 1:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr=(
                    '{"ok":false,"error":{"code":"TIMEOUT",'
                    '"message":"Browser command timed out"}}'
                ),
            )
        output_dir = Path(command[command.index("--output") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "video.mp4").write_bytes(b"video")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='[{"status":"success"}]',
            stderr="",
        )

    mock_run.side_effect = run
    client = OpenCliClient(
        OpenCliSettings(
            command=("opencli",),
            download_retries=2,
            download_retry_backoff_seconds=0.5,
        )
    )

    _, result = client.download("BV1abc", tmp_path / "video")

    assert mock_run.call_count == 2
    mock_sleep.assert_called_once_with(0.5)
    assert result["retry_index"] == 1
    assert result["attempt_count"] == 2


@patch("video_subtitle.platforms.bilibili.time.sleep")
@patch("video_subtitle.platforms.bilibili.subprocess.run")
def test_download_reuses_media_that_completed_after_unknown_result(
    mock_run,
    mock_sleep,
    tmp_path: Path,
) -> None:
    def timed_out_after_write(command, **kwargs):
        output_dir = Path(command[command.index("--output") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "video.mp4").write_bytes(b"completed")
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr=(
                '{"ok":false,"error":{"code":"command_result_unknown",'
                '"message":"Browser command result unknown"}}'
            ),
        )

    mock_run.side_effect = timed_out_after_write
    client = OpenCliClient(
        OpenCliSettings(
            command=("opencli",),
            download_retries=2,
            download_retry_backoff_seconds=0,
        )
    )

    path, result = client.download(
        "BV1abc",
        tmp_path / "job",
        cache_dir=tmp_path / "cache",
        cache_key="BV1abc",
    )

    assert path.read_bytes() == b"completed"
    assert mock_run.call_count == 1
    mock_sleep.assert_not_called()
    assert result["cache_hit"] is True
    assert result["cache_state"] == "recovered_after_error"
    assert result["retry_index"] == 1
