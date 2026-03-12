"""Shared fixtures for integration tests."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from reeln.models.config import VideoConfig
from reeln.models.game import GameInfo

# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------

_ENV_VARS_TO_CLEAR = [
    "REELN_CONFIG",
    "REELN_PROFILE",
    "REELN_SPORT",
    "REELN_VIDEO_CODEC",
    "REELN_VIDEO_CRF",
    "REELN_VIDEO_PRESET",
    "REELN_VIDEO_AUDIO_CODEC",
    "REELN_VIDEO_AUDIO_BITRATE",
    "REELN_VIDEO_FFMPEG_PATH",
    "REELN_PATHS_OUTPUT_DIR",
    "REELN_PATHS_TEMP_DIR",
    "REELN_LOG_FORMAT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear reeln-related env vars to isolate from user's real environment."""
    for var in _ENV_VARS_TO_CLEAR:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_real_plugins() -> Generator[None, None, None]:
    """Prevent real plugins from loading during integration tests.

    Without this, activate_plugins() loads plugins from the user's real
    config (e.g. google with create_livestream=true), causing side effects
    like creating actual YouTube livestreams on every test run.
    """
    with patch("reeln.plugins.loader.load_enabled_plugins", return_value={}):
        yield


# ---------------------------------------------------------------------------
# Game info fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hockey_game_info() -> GameInfo:
    """A hockey game info instance."""
    return GameInfo(
        date="2026-02-26",
        home_team="roseville",
        away_team="mahtomedi",
        sport="hockey",
    )


@pytest.fixture()
def basketball_game_info() -> GameInfo:
    """A basketball game info instance."""
    return GameInfo(
        date="2026-02-26",
        home_team="lakers",
        away_team="celtics",
        sport="basketball",
    )


# ---------------------------------------------------------------------------
# Video config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def custom_video_config() -> VideoConfig:
    """A non-default VideoConfig for testing config flow."""
    return VideoConfig(codec="libx265", crf=22, audio_codec="opus")


# ---------------------------------------------------------------------------
# Dummy video file factory
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_dummy_videos() -> Callable[..., list[Path]]:
    """Factory that creates empty video files in a directory."""

    def _factory(directory: Path, count: int = 3, ext: str = ".mkv") -> list[Path]:
        files: list[Path] = []
        for i in range(1, count + 1):
            f = directory / f"replay_{i:02d}{ext}"
            f.touch()
            files.append(f)
        return files

    return _factory


# ---------------------------------------------------------------------------
# Mock ffmpeg subprocess
# ---------------------------------------------------------------------------


def _mock_ffmpeg_success(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Subprocess mock that always succeeds."""
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


@pytest.fixture()
def mock_ffmpeg_run() -> Generator[list[list[str]], None, None]:
    """Patch subprocess.run in reeln.core.ffmpeg, yielding captured command lists.

    Each ffmpeg invocation appends its command list to the yielded list.
    """
    captured: list[list[str]] = []

    def _capture(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("reeln.core.ffmpeg.subprocess.run", side_effect=_capture):
        yield captured


# ---------------------------------------------------------------------------
# Real ffmpeg fixtures (for @pytest.mark.integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_ffmpeg_path() -> Path:
    """Discover real ffmpeg, skip test if unavailable."""
    from reeln.core.ffmpeg import discover_ffmpeg

    try:
        return discover_ffmpeg()
    except Exception:
        pytest.skip("ffmpeg not available")
        raise  # unreachable, keeps mypy happy


@pytest.fixture()
def make_real_test_video(
    real_ffmpeg_path: Path,
) -> Callable[..., Path]:
    """Factory that generates a real test video using ffmpeg -f lavfi."""

    def _factory(output: Path, duration: float = 1.0) -> Path:
        cmd = [
            str(real_ffmpeg_path),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        return output

    return _factory
