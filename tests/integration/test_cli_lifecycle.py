"""CLI-layer integration tests for the full command stack.

Full stack through CliRunner. load_config reads real config files.
Only discover_ffmpeg is mocked — no real ffmpeg required.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from reeln.cli import app
from reeln.core.highlights import create_game_directory, load_game_state
from reeln.core.segment import segment_dir_name
from reeln.models.game import GameInfo

runner = CliRunner()
_FFMPEG = Path("/usr/bin/ffmpeg")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_discover() -> Path:
    return _FFMPEG


def _mock_subprocess_success(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def _populate_segment(game_dir: Path, sport: str, seg_num: int, count: int = 3) -> None:
    """Create dummy video files in a segment directory."""
    alias = segment_dir_name(sport, seg_num)
    seg_dir = game_dir / alias
    for i in range(1, count + 1):
        (seg_dir / f"replay_{i:02d}.mkv").touch()


def _touch_segment_output(game_dir: Path, sport: str, seg_num: int, date: str) -> None:
    """Touch the expected segment merge output file."""
    alias = segment_dir_name(sport, seg_num)
    (game_dir / alias / f"{alias}_{date}.mkv").touch()


def _write_config(path: Path, data: dict[str, Any]) -> Path:
    """Write a JSON config file and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI game lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCLIGameLifecycle:
    """Full CLI pipeline: init → segment → highlights."""

    def test_full_pipeline_hockey(self, tmp_path: Path) -> None:
        """CLI init → segment 1,2,3 → highlights; verify game.json at each step."""
        with (
            patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover),
            patch("reeln.core.ffmpeg.subprocess.run", side_effect=_mock_subprocess_success),
        ):
            # Init
            result = runner.invoke(
                app,
                [
                    "game",
                    "init",
                    "roseville",
                    "mahtomedi",
                    "-s",
                    "hockey",
                    "--date",
                    "2026-02-26",
                    "-o",
                    str(tmp_path),
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Game directory:" in result.output

            game_dir = tmp_path / "2026-02-26_roseville_vs_mahtomedi"
            assert game_dir.is_dir()

            # Segment 1, 2, 3
            for seg in range(1, 4):
                _populate_segment(game_dir, "hockey", seg)
                result = runner.invoke(
                    app,
                    [
                        "game",
                        "segment",
                        str(seg),
                        "-o",
                        str(game_dir),
                    ],
                )
                assert result.exit_code == 0, result.output
                assert "Merge complete" in result.output
                _touch_segment_output(game_dir, "hockey", seg, "2026-02-26")

            state = load_game_state(game_dir)
            assert state.segments_processed == [1, 2, 3]

            # Highlights
            result = runner.invoke(
                app,
                [
                    "game",
                    "highlights",
                    "-o",
                    str(game_dir),
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Highlights merge complete" in result.output

            state = load_game_state(game_dir)
            assert state.highlighted is True

    def test_config_file_flows_to_ffmpeg_command(self, tmp_path: Path) -> None:
        """--config with libx265/crf=22 settings flow into ffmpeg args."""
        config_file = _write_config(
            tmp_path / "custom.json",
            {
                "config_version": 1,
                "video": {"codec": "libx265", "crf": 22, "audio_codec": "opus"},
            },
        )

        captured: list[list[str]] = []

        def capture_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            captured.append(list(cmd))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        # Init a game
        info = GameInfo(
            date="2026-02-26",
            home_team="roseville",
            away_team="mahtomedi",
            sport="hockey",
        )
        game_dir = create_game_directory(tmp_path / "games", info)

        # Put mixed containers to force re-encode so config values appear in command
        seg_dir = game_dir / "period-1"
        (seg_dir / "replay_01.mkv").touch()
        (seg_dir / "replay_02.mp4").touch()

        with (
            patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover),
            patch("reeln.core.ffmpeg.subprocess.run", side_effect=capture_run),
        ):
            result = runner.invoke(
                app,
                [
                    "game",
                    "segment",
                    "1",
                    "-o",
                    str(game_dir),
                    "--config",
                    str(config_file),
                ],
            )
            assert result.exit_code == 0, result.output

        assert len(captured) == 1
        cmd = captured[0]
        assert "libx265" in cmd
        assert "opus" in cmd
        crf_idx = cmd.index("-crf")
        assert cmd[crf_idx + 1] == "22"

    def test_env_var_override_flows_to_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """REELN_VIDEO_CRF=30 overrides default and appears in ffmpeg command."""
        monkeypatch.setenv("REELN_VIDEO_CRF", "30")

        captured: list[list[str]] = []

        def capture_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            captured.append(list(cmd))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        info = GameInfo(
            date="2026-02-26",
            home_team="roseville",
            away_team="mahtomedi",
            sport="hockey",
        )
        game_dir = create_game_directory(tmp_path, info)

        # Mixed containers to force re-encode
        seg_dir = game_dir / "period-1"
        (seg_dir / "replay_01.mkv").touch()
        (seg_dir / "replay_02.mp4").touch()

        with (
            patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover),
            patch("reeln.core.ffmpeg.subprocess.run", side_effect=capture_run),
        ):
            result = runner.invoke(
                app,
                [
                    "game",
                    "segment",
                    "1",
                    "-o",
                    str(game_dir),
                ],
            )
            assert result.exit_code == 0, result.output

        assert len(captured) == 1
        cmd = captured[0]
        crf_idx = cmd.index("-crf")
        assert cmd[crf_idx + 1] == "30"

    def test_config_output_dir_used_as_default(self, tmp_path: Path) -> None:
        """paths.output_dir from config used when -o is omitted."""
        game_base = tmp_path / "games"
        config_file = _write_config(
            tmp_path / "with_path.json",
            {
                "config_version": 1,
                "paths": {"output_dir": str(game_base)},
            },
        )

        with (
            patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover),
            patch("reeln.core.ffmpeg.subprocess.run", side_effect=_mock_subprocess_success),
        ):
            result = runner.invoke(
                app,
                [
                    "game",
                    "init",
                    "roseville",
                    "mahtomedi",
                    "-s",
                    "hockey",
                    "--date",
                    "2026-02-26",
                    "--config",
                    str(config_file),
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Game directory:" in result.output

        assert (game_base / "2026-02-26_roseville_vs_mahtomedi").is_dir()


# ---------------------------------------------------------------------------
# CLI error scenarios
# ---------------------------------------------------------------------------


class TestCLIErrorScenarios:
    """CLI error paths produce correct exit codes and messages."""

    def test_init_with_invalid_sport(self, tmp_path: Path) -> None:
        """Invalid sport → exit 1, error message."""
        result = runner.invoke(
            app,
            [
                "game",
                "init",
                "a",
                "b",
                "-s",
                "curling",
                "-o",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 1
        assert "Unknown sport" in result.output

    def test_segment_with_no_game_state(self, tmp_path: Path) -> None:
        """No game.json → error."""
        with patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover):
            result = runner.invoke(
                app,
                [
                    "game",
                    "segment",
                    "1",
                    "-o",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 1
        assert "No game directory found" in result.output

    def test_segment_with_no_videos(self, tmp_path: Path) -> None:
        """Empty segment dir → "No video files" error."""
        info = GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        )
        game_dir = create_game_directory(tmp_path, info)

        with patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover):
            result = runner.invoke(
                app,
                [
                    "game",
                    "segment",
                    "1",
                    "-o",
                    str(game_dir),
                ],
            )
        assert result.exit_code == 1
        assert "No video files" in result.output

    def test_highlights_with_no_segments(self, tmp_path: Path) -> None:
        """No segment highlight files → "No segment highlight files" error."""
        info = GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        )
        game_dir = create_game_directory(tmp_path, info)

        with patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover):
            result = runner.invoke(
                app,
                [
                    "game",
                    "highlights",
                    "-o",
                    str(game_dir),
                ],
            )
        assert result.exit_code == 1
        assert "No segment highlight files" in result.output

    def test_reeln_config_env_var_selects_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """REELN_CONFIG env var loads the correct config file."""
        config_file = _write_config(
            tmp_path / "env_config.json",
            {
                "config_version": 1,
                "sport": "basketball",
                "paths": {"output_dir": str(tmp_path / "out")},
            },
        )
        monkeypatch.setenv("REELN_CONFIG", str(config_file))

        with (
            patch("reeln.commands.game.discover_ffmpeg", side_effect=_mock_discover),
            patch("reeln.core.ffmpeg.subprocess.run", side_effect=_mock_subprocess_success),
        ):
            result = runner.invoke(
                app,
                [
                    "game",
                    "init",
                    "lakers",
                    "celtics",
                    "-s",
                    "basketball",
                    "--date",
                    "2026-02-26",
                ],
            )
            assert result.exit_code == 0, result.output

        # Config's output_dir was used
        assert (tmp_path / "out" / "2026-02-26_lakers_vs_celtics").is_dir()
