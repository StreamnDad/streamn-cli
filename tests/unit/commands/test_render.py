"""Tests for the render command group: short, preview, apply, reel."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from reeln.cli import app
from reeln.models.game import (
    GameEvent,
    GameInfo,
    GameState,
    RenderEntry,
    game_state_to_dict,
)
from reeln.models.render_plan import IterationResult, RenderResult

runner = CliRunner()


def _write_game_state(game_dir: Path, state: GameState) -> None:
    """Write a game.json in the given directory."""
    data = game_state_to_dict(state)
    (game_dir / "game.json").write_text(json.dumps(data, indent=2))


def _mock_result(tmp_path: Path) -> RenderResult:
    return RenderResult(
        output=tmp_path / "out.mp4",
        duration_seconds=30.0,
        file_size_bytes=1024000,
    )


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_render_help_lists_commands() -> None:
    result = runner.invoke(app, ["render", "--help"])
    assert result.exit_code == 0
    assert "short" in result.output
    assert "preview" in result.output
    assert "reel" in result.output


# ---------------------------------------------------------------------------
# render short
# ---------------------------------------------------------------------------


def _config_with_source(
    tmp_path: Path,
    source_dir: Path,
    source_glob: str | None = None,
) -> Path:
    """Write a config file with paths.source_dir (and optional source_glob)."""
    paths: dict[str, str | None] = {"source_dir": str(source_dir)}
    if source_glob is not None:
        paths["source_glob"] = source_glob
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"paths": paths}))
    return cfg


def test_render_short_no_clip_uses_latest(tmp_path: Path) -> None:
    """When no clip argument, use the most recently modified matching file."""
    import time

    src = tmp_path / "recordings"
    src.mkdir()
    older = src / "Replay_old.mkv"
    older.write_bytes(b"old")
    time.sleep(0.05)
    newer = src / "Replay_new.mkv"
    newer.write_bytes(b"new")
    cfg = _config_with_source(tmp_path, src)
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            "--dry-run",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 0
    assert "Replay_new.mkv" in result.output


def test_render_short_no_clip_no_source_dir(tmp_path: Path) -> None:
    """Error when no clip and source_dir not configured."""
    cfg = tmp_path / "empty.json"
    cfg.write_text(json.dumps({"config_version": 1}))
    result = runner.invoke(app, ["render", "short", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "source_dir not configured" in result.output


def test_render_short_no_clip_no_match(tmp_path: Path) -> None:
    """Error when source_dir has no files matching the default glob."""
    src = tmp_path / "recordings"
    src.mkdir()
    (src / "Manual_clip.mkv").write_bytes(b"data")
    cfg = _config_with_source(tmp_path, src)
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1
    assert "No files matching" in result.output


def test_render_short_no_clip_skips_dirs_and_non_matching(tmp_path: Path) -> None:
    """Subdirectories and non-matching files are skipped."""
    src = tmp_path / "recordings"
    src.mkdir()
    (src / "Replay_dir.mkv").mkdir()  # directory, not a file
    (src / "notes.txt").write_text("hello")
    (src / "Replay_clip.mkv").write_bytes(b"video")
    cfg = _config_with_source(tmp_path, src)
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            "--dry-run",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 0
    assert "Replay_clip.mkv" in result.output


def test_render_short_no_clip_custom_glob(tmp_path: Path) -> None:
    """Custom source_glob overrides the default pattern."""
    import time

    src = tmp_path / "recordings"
    src.mkdir()
    # Default glob would miss these (no Replay_ prefix)
    (src / "Game_old.mp4").write_bytes(b"old")
    time.sleep(0.05)
    (src / "Game_new.mp4").write_bytes(b"new")
    # This matches default but not custom glob
    (src / "Replay_2026.mkv").write_bytes(b"replay")
    cfg = _config_with_source(tmp_path, src, source_glob="Game_*.mp4")
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            "--dry-run",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 0
    assert "Game_new.mp4" in result.output


def test_render_short_no_clip_custom_glob_no_match(tmp_path: Path) -> None:
    """Error when custom source_glob matches nothing."""
    src = tmp_path / "recordings"
    src.mkdir()
    (src / "Replay_clip.mkv").write_bytes(b"data")
    cfg = _config_with_source(tmp_path, src, source_glob="Game_*.mp4")
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1
    assert "No files matching" in result.output
    assert "Game_*.mp4" in result.output


def test_render_short_dry_run(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "Input:" in result.output
    assert "Size: 1080x1920" in result.output


def test_render_short_dry_run_crop_mode(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--crop",
            "crop",
        ],
    )
    assert result.exit_code == 0
    assert "Crop mode: crop" in result.output


def test_render_short_dry_run_square(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--format",
            "square",
        ],
    )
    assert result.exit_code == 0
    assert "Size: 1080x1080" in result.output


def test_render_short_dry_run_custom_size(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--size",
            "720x1280",
        ],
    )
    assert result.exit_code == 0
    assert "Size: 720x1280" in result.output


def test_render_short_dry_run_with_speed(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--speed",
            "0.5",
        ],
    )
    assert result.exit_code == 0
    assert "Speed: 0.5x" in result.output


def test_render_short_dry_run_with_lut_and_subtitle(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    lut = tmp_path / "grade.cube"
    lut.touch()
    sub = tmp_path / "subs.ass"
    sub.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--lut",
            str(lut),
            "--subtitle",
            str(sub),
        ],
    )
    assert result.exit_code == 0
    assert "LUT:" in result.output
    assert "Subtitle:" in result.output


def test_render_short_with_output(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    out = tmp_path / "custom.mp4"
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert str(out) in result.output


def test_render_short_executes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_renderer_cls,
    ):
        mock_renderer_cls.return_value.render.return_value = mock_result
        result = runner.invoke(app, ["render", "short", str(clip)])

    assert result.exit_code == 0
    assert "Render complete" in result.output
    assert "Duration: 30.0s" in result.output
    assert "File size:" in result.output


def test_render_short_render_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    from reeln.core.errors import FFmpegError

    with patch("reeln.core.ffmpeg.discover_ffmpeg", side_effect=FFmpegError("not found")):
        result = runner.invoke(app, ["render", "short", str(clip)])

    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_short_invalid_crop_mode(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--crop",
            "invalid",
        ],
    )
    assert result.exit_code == 1
    assert "Unknown crop mode" in result.output


def test_render_short_invalid_size_format(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--size",
            "invalid",
        ],
    )
    assert result.exit_code != 0


def test_render_short_invalid_size_values(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--size",
            "axb",
        ],
    )
    assert result.exit_code != 0


def test_render_short_unknown_format(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--format",
            "widescreen",
        ],
    )
    assert result.exit_code != 0


def test_render_short_invalid_anchor(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--anchor",
            "invalid",
        ],
    )
    assert result.exit_code != 0


def test_render_short_custom_anchor(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--dry-run",
            "--anchor",
            "0.3,0.7",
        ],
    )
    assert result.exit_code == 0


def test_render_short_invalid_custom_anchor(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--anchor",
            "a,b",
        ],
    )
    assert result.exit_code != 0


def test_render_short_named_anchor(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    for anchor in ["center", "top", "bottom", "left", "right"]:
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--dry-run",
                "--anchor",
                anchor,
            ],
        )
        assert result.exit_code == 0, f"Failed for anchor={anchor}"


def test_render_short_validation_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--size",
            "1081x1920",
        ],
    )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_short_config_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    bad_config = tmp_path / "bad.json"
    bad_config.write_text("not json!")
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--config",
            str(bad_config),
        ],
    )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_short_no_duration_or_size(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    mock_result = RenderResult(output=tmp_path / "out.mp4")
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(app, ["render", "short", str(clip)])

    assert result.exit_code == 0
    assert "Duration:" not in result.output
    assert "File size:" not in result.output


# ---------------------------------------------------------------------------
# render short --game-dir (Stage B)
# ---------------------------------------------------------------------------


def test_render_short_with_game_dir(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-26T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(game_dir),
            ],
        )

    assert result.exit_code == 0
    assert "Render complete" in result.output
    # Verify render entry was saved
    saved = json.loads((game_dir / "game.json").read_text())
    assert len(saved["renders"]) == 1


def test_render_short_game_dir_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    bad_dir = tmp_path / "nonexistent"

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(bad_dir),
            ],
        )

    assert result.exit_code == 0
    assert "Warning:" in result.output


# ---------------------------------------------------------------------------
# render short — auto-discover game dir
# ---------------------------------------------------------------------------


def test_render_short_auto_discovers_game_dir(tmp_path: Path) -> None:
    """When --game-dir is not passed, auto-discover from config output_dir."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    game_dir = output_dir / "2026-02-28_a_vs_b"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"paths": {"output_dir": str(output_dir)}}))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    assert "Render complete" in result.output
    saved = json.loads((game_dir / "game.json").read_text())
    assert len(saved["renders"]) == 1


def test_render_short_no_game_dir_skips_tracking(tmp_path: Path) -> None:
    """When no game dir found, render still succeeds without tracking."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"config_version": 1}))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    assert "Render complete" in result.output


def test_render_short_output_dir_not_a_dir(tmp_path: Path) -> None:
    """When output_dir doesn't exist, skip tracking silently."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"paths": {"output_dir": str(tmp_path / "nonexistent")}}))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    assert "Render complete" in result.output


def test_render_short_output_dir_no_games(tmp_path: Path) -> None:
    """When output_dir has no game subdirs, skip tracking silently."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "random_dir").mkdir()

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"paths": {"output_dir": str(output_dir)}}))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    assert "Render complete" in result.output


def test_render_short_auto_discover_direct_game_dir(tmp_path: Path) -> None:
    """When output_dir itself contains game.json, use it directly."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"paths": {"output_dir": str(game_dir)}}))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    saved = json.loads((game_dir / "game.json").read_text())
    assert len(saved["renders"]) == 1


# ---------------------------------------------------------------------------
# render preview
# ---------------------------------------------------------------------------


def test_render_preview_dry_run(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "preview",
            str(clip),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    # Preview uses half resolution
    assert "Size: 540x960" in result.output


def test_render_preview_executes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(app, ["render", "preview", str(clip)])

    assert result.exit_code == 0
    assert "Render complete" in result.output


def test_render_preview_default_output_suffix(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    result = runner.invoke(
        app,
        [
            "render",
            "preview",
            str(clip),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "clip_preview.mp4" in result.output


# ---------------------------------------------------------------------------
# render short/preview --render-profile
# ---------------------------------------------------------------------------


def test_render_short_with_render_profile(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, "slowmo", speed=0.5)
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Speed: 0.5x" in result.output
    assert "Profile: slowmo" in result.output


def test_render_short_render_profile_overrides_crop(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, "cropped", speed=1.0, crop_mode="crop")
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--render-profile",
            "cropped",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Crop mode: crop" in result.output


def test_render_short_render_profile_not_found(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"config_version": 1}))
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--render-profile",
            "nonexistent",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_render_preview_with_render_profile(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, "slowmo", speed=0.5)
    result = runner.invoke(
        app,
        [
            "render",
            "preview",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Speed: 0.5x" in result.output
    assert "Profile: slowmo" in result.output


def test_render_short_render_profile_executes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, "slowmo", speed=0.5)
    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--render-profile",
                "slowmo",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Render complete" in result.output


# ---------------------------------------------------------------------------
# --player / --assists flags + subtitle gap fix
# ---------------------------------------------------------------------------


def test_short_profile_subtitle_template_renders(tmp_path: Path) -> None:
    """Bug fix: subtitle_template in render profile was silently dropped in _do_short()."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{player}}", encoding="utf-8")

    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="Roseville",
            away_team="Mahtomedi",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--render-profile",
            "overlay",
            "--game-dir",
            str(game_dir),
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_short_player_flag_populates_overlay_without_game(tmp_path: Path) -> None:
    """--player populates overlay context even without game state."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{goal_scorer_text}}", encoding="utf-8")

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")), patch(
        "reeln.core.ffmpeg.probe_duration", return_value=10.0
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--render-profile",
                "overlay",
                "--player",
                "#17 Smith",
                "--assists",
                "#22 Jones, #5 Brown",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_short_assists_flag_populates_overlay_without_game(tmp_path: Path) -> None:
    """--assists populates overlay context even without game state."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Assists: {{goal_assist_1}}", encoding="utf-8")

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")), patch(
        "reeln.core.ffmpeg.probe_duration", return_value=10.0
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--render-profile",
                "overlay",
                "--assists",
                "#22 Jones",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_short_player_flag_overrides_event_data(tmp_path: Path) -> None:
    """CLI --player overrides player from game event metadata."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{goal_scorer_text}}", encoding="utf-8")

    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-28", home_team="A", away_team="B", sport="hockey"
        ),
        created_at="2026-02-28T12:00:00+00:00",
        events=[
            GameEvent(
                id="ev1",
                clip="clip.mkv",
                segment_number=1,
                event_type="goal",
                player="OldPlayer",
                metadata={"assists": "#99 OldAssist"},
            ),
        ],
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")), patch(
        "reeln.core.ffmpeg.probe_duration", return_value=10.0
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--render-profile",
                "overlay",
                "--game-dir",
                str(game_dir),
                "--event",
                "ev1",
                "--player",
                "NewPlayer",
                "--assists",
                "#11 NewAssist",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_short_player_flag_without_render_profile_is_noop(tmp_path: Path) -> None:
    """--player without --render-profile is ignored (no subtitle template to fill)."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"config_version": 1}))

    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--player",
            "Smith",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Subtitle:" not in result.output


def test_preview_player_flag(tmp_path: Path) -> None:
    """--player flag works on render preview."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{goal_scorer_text}}", encoding="utf-8")

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")), patch(
        "reeln.core.ffmpeg.probe_duration", return_value=10.0
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "preview",
                str(clip),
                "--render-profile",
                "overlay",
                "--player",
                "#17 Smith",
                "--assists",
                "#22",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_apply_player_flag_without_game_dir(tmp_path: Path) -> None:
    """--player on render apply populates overlay without game dir."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{goal_scorer_text}}", encoding="utf-8")

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")), patch(
        "reeln.core.ffmpeg.probe_duration", return_value=10.0
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "overlay",
                "--player",
                "#17 Smith",
                "--assists",
                "#22 Jones",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_apply_player_flag_overrides_event(tmp_path: Path) -> None:
    """--player on render apply overrides event-sourced player."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{goal_scorer_text}}", encoding="utf-8")

    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-28", home_team="A", away_team="B", sport="hockey"
        ),
        created_at="2026-02-28T12:00:00+00:00",
        events=[
            GameEvent(
                id="ev1", clip="x.mkv", segment_number=1,
                event_type="goal", player="OldPlayer",
            ),
        ],
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")), patch(
        "reeln.core.ffmpeg.probe_duration", return_value=10.0
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "overlay",
                "--game-dir",
                str(game_dir),
                "--event",
                "ev1",
                "--player",
                "NewPlayer",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_short_subtitle_temp_cleanup_after_render(tmp_path: Path) -> None:
    """Rendered subtitle temp files in _do_short() are cleaned up after render."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    template = tmp_path / "overlay.ass"
    template.write_text("Hello", encoding="utf-8")

    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-28", home_team="A", away_team="B", sport="hockey"
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--render-profile",
                "overlay",
                "--game-dir",
                str(game_dir),
                "--output",
                str(out_dir / "out.mp4"),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    # Temp .ass files should be cleaned up
    ass_files = list(out_dir.glob("*.ass"))
    assert ass_files == []


def test_short_profile_no_subtitle_template_no_subtitle(tmp_path: Path) -> None:
    """Profile without subtitle_template doesn't trigger subtitle resolution."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, "speedonly", speed=0.5)

    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--render-profile",
            "speedonly",
            "--player",
            "#17 Smith",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Subtitle:" not in result.output
    assert "Speed: 0.5x" in result.output


def test_apply_subtitle_without_game_info_uses_empty_context(tmp_path: Path) -> None:
    """render apply with subtitle_template but no game_info uses empty TemplateContext."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Static overlay", encoding="utf-8")

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "overlay",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


# ---------------------------------------------------------------------------
# render reel
# ---------------------------------------------------------------------------


def _setup_reel(tmp_path: Path) -> tuple[Path, Path]:
    """Create a game dir with one render entry and the rendered file."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    rendered = game_dir / "clip_short.mp4"
    rendered.write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="roseville",
            away_team="mahtomedi",
            sport="hockey",
        ),
        renders=[
            RenderEntry(
                input="clip.mkv",
                output="clip_short.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
            ),
        ],
    )
    _write_game_state(game_dir, state)
    return game_dir, rendered


def test_render_reel_dry_run(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "Renders: 1" in result.output
    assert "clip_short.mp4" in result.output


def test_render_reel_executes(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    concat_file = game_dir / "concat.txt"
    concat_file.touch()
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.ffmpeg.write_concat_file", return_value=concat_file),
        patch("reeln.core.ffmpeg.run_ffmpeg"),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "reel",
                "--game-dir",
                str(game_dir),
            ],
        )

    assert result.exit_code == 0
    assert "Reel assembly complete" in result.output


def test_render_reel_with_segment_filter(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--segment",
            "1",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Renders: 1" in result.output
    assert "period-1_reel.mp4" in result.output


def test_render_reel_segment_no_match(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--segment",
            "99",
        ],
    )
    assert result.exit_code == 1
    assert "No rendered shorts found" in result.output


def test_render_reel_no_renders(tmp_path: Path) -> None:
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
    )
    _write_game_state(game_dir, state)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
        ],
    )
    assert result.exit_code == 1
    assert "No rendered shorts found" in result.output


def test_render_reel_missing_file(tmp_path: Path) -> None:
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        renders=[
            RenderEntry(
                input="clip.mkv",
                output="missing.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
            ),
        ],
    )
    _write_game_state(game_dir, state)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
        ],
    )
    assert result.exit_code == 1
    assert "Rendered file not found" in result.output


def test_render_reel_custom_output(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    custom_out = tmp_path / "my_reel.mp4"
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--output",
            str(custom_out),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert str(custom_out) in result.output


def test_render_reel_default_output_name(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "roseville_vs_mahtomedi_2026-02-26_reel.mp4" in result.output


def test_render_reel_game_state_error(tmp_path: Path) -> None:
    bad_dir = tmp_path / "nonexistent"
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(bad_dir),
        ],
    )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_reel_config_error(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    bad_config = tmp_path / "bad.json"
    bad_config.write_text("invalid!")
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--config",
            str(bad_config),
        ],
    )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_reel_ffmpeg_error(tmp_path: Path) -> None:
    game_dir, _ = _setup_reel(tmp_path)
    from reeln.core.errors import FFmpegError

    with patch("reeln.core.ffmpeg.discover_ffmpeg", side_effect=FFmpegError("not found")):
        result = runner.invoke(
            app,
            [
                "render",
                "reel",
                "--game-dir",
                str(game_dir),
            ],
        )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_reel_mixed_formats(tmp_path: Path) -> None:
    """Mixed extensions trigger re-encode mode."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "a.mp4").write_bytes(b"video")
    (game_dir / "b.mkv").write_bytes(b"video")
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        renders=[
            RenderEntry(
                input="a.mkv",
                output="a.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
            ),
            RenderEntry(
                input="b.mkv",
                output="b.mkv",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
            ),
        ],
    )
    _write_game_state(game_dir, state)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "re-encode" in result.output


# ---------------------------------------------------------------------------
# render short — event linking
# ---------------------------------------------------------------------------


def test_render_short_auto_links_event(tmp_path: Path) -> None:
    """Render auto-links to an event when the clip matches an event's clip path."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    clip = game_dir / "period-1" / "Replay_001.mkv"
    clip.parent.mkdir()
    clip.write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
        events=[
            GameEvent(
                id="ev1234567890",
                clip="period-1/Replay_001.mkv",
                segment_number=1,
                event_type="goal",
            ),
        ],
    )
    _write_game_state(game_dir, state)

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(game_dir),
            ],
        )

    assert result.exit_code == 0
    saved = json.loads((game_dir / "game.json").read_text())
    assert saved["renders"][0]["event_id"] == "ev1234567890"


def test_render_short_no_matching_event(tmp_path: Path) -> None:
    """Render entry has empty event_id when no event matches the clip."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    clip = tmp_path / "external_clip.mkv"
    clip.write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
        events=[
            GameEvent(
                id="ev1234567890",
                clip="period-1/Replay_001.mkv",
                segment_number=1,
            ),
        ],
    )
    _write_game_state(game_dir, state)

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(game_dir),
            ],
        )

    assert result.exit_code == 0
    saved = json.loads((game_dir / "game.json").read_text())
    assert saved["renders"][0]["event_id"] == ""


def test_render_short_explicit_event(tmp_path: Path) -> None:
    """--event flag explicitly links the render to an event ID."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    clip = tmp_path / "clip.mkv"
    clip.write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(game_dir),
                "--event",
                "custom_event_id",
            ],
        )

    assert result.exit_code == 0
    saved = json.loads((game_dir / "game.json").read_text())
    assert saved["renders"][0]["event_id"] == "custom_event_id"


def test_render_short_explicit_event_overrides_auto(tmp_path: Path) -> None:
    """--event flag takes precedence over auto-link detection."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    clip = game_dir / "period-1" / "Replay_001.mkv"
    clip.parent.mkdir()
    clip.write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
        events=[
            GameEvent(
                id="auto_event_id",
                clip="period-1/Replay_001.mkv",
                segment_number=1,
            ),
        ],
    )
    _write_game_state(game_dir, state)

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(game_dir),
                "--event",
                "explicit_event_id",
            ],
        )

    assert result.exit_code == 0
    saved = json.loads((game_dir / "game.json").read_text())
    assert saved["renders"][0]["event_id"] == "explicit_event_id"


# ---------------------------------------------------------------------------
# render reel — event-type filtering
# ---------------------------------------------------------------------------


def test_render_reel_event_type_filter(tmp_path: Path) -> None:
    """--event-type filters renders by linked event type."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "goal_short.mp4").write_bytes(b"video")
    (game_dir / "save_short.mp4").write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        events=[
            GameEvent(id="ev_goal", clip="period-1/r1.mkv", segment_number=1, event_type="goal"),
            GameEvent(id="ev_save", clip="period-1/r2.mkv", segment_number=1, event_type="save"),
        ],
        renders=[
            RenderEntry(
                input="period-1/r1.mkv",
                output="goal_short.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
                event_id="ev_goal",
            ),
            RenderEntry(
                input="period-1/r2.mkv",
                output="save_short.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
                event_id="ev_save",
            ),
        ],
    )
    _write_game_state(game_dir, state)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--event-type",
            "goal",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Renders: 1" in result.output
    assert "goal_short.mp4" in result.output
    assert "save_short.mp4" not in result.output


def test_render_reel_event_type_no_match(tmp_path: Path) -> None:
    """--event-type with no matching events returns error."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "clip_short.mp4").write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        events=[
            GameEvent(id="ev_save", clip="period-1/r1.mkv", segment_number=1, event_type="save"),
        ],
        renders=[
            RenderEntry(
                input="period-1/r1.mkv",
                output="clip_short.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
                event_id="ev_save",
            ),
        ],
    )
    _write_game_state(game_dir, state)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--event-type",
            "goal",
        ],
    )
    assert result.exit_code == 1
    assert "No rendered shorts found" in result.output


def test_render_reel_event_type_unlinked_renders_excluded(tmp_path: Path) -> None:
    """Renders without event_id are excluded when --event-type is used."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "clip_short.mp4").write_bytes(b"video")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        events=[
            GameEvent(id="ev_goal", clip="period-1/r1.mkv", segment_number=1, event_type="goal"),
        ],
        renders=[
            RenderEntry(
                input="period-1/r1.mkv",
                output="clip_short.mp4",
                segment_number=1,
                format="1080x1920",
                crop_mode="pad",
                rendered_at="2026-02-26T12:00:00+00:00",
                event_id="",  # unlinked
            ),
        ],
    )
    _write_game_state(game_dir, state)
    result = runner.invoke(
        app,
        [
            "render",
            "reel",
            "--game-dir",
            str(game_dir),
            "--event-type",
            "goal",
        ],
    )
    assert result.exit_code == 1
    assert "No rendered shorts found" in result.output


# ---------------------------------------------------------------------------
# render apply
# ---------------------------------------------------------------------------


def _config_with_profile(
    tmp_path: Path,
    profile_name: str = "slowmo",
    speed: float = 0.5,
    **kwargs: object,
) -> Path:
    """Write a config file with a render profile."""
    profile_data: dict[str, object] = {"speed": speed, **kwargs}
    cfg_data = {"render_profiles": {profile_name: profile_data}}
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))
    return cfg


def test_render_apply_help() -> None:
    result = runner.invoke(app, ["render", "apply", "--help"])
    assert result.exit_code == 0
    assert "--render-profile" in result.output


def test_render_apply_dry_run(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "Profile: slowmo" in result.output
    assert "Speed: 0.5x" in result.output


def test_render_apply_default_output(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "clip_slowmo.mp4" in result.output


def test_render_apply_custom_output(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    out = tmp_path / "custom.mp4"
    cfg = _config_with_profile(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--output",
            str(out),
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert str(out) in result.output


def test_render_apply_with_lut(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, speed=1.0, lut="warm.cube")
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "LUT: warm.cube" in result.output


def test_render_apply_executes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path)
    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Render complete" in result.output
    assert "Duration: 30.0s" in result.output


def test_render_apply_no_duration(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path)
    mock_result = RenderResult(output=tmp_path / "out.mp4")
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Duration:" not in result.output
    assert "File size:" not in result.output


def test_render_apply_unknown_profile(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"config_version": 1}))
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "nonexistent",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_render_apply_config_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    bad_cfg = tmp_path / "bad.json"
    bad_cfg.write_text("invalid!")
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(bad_cfg),
        ],
    )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_apply_ffmpeg_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path)
    from reeln.core.errors import FFmpegError

    with patch("reeln.core.ffmpeg.discover_ffmpeg", side_effect=FFmpegError("not found")):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_render_apply_with_game_dir_and_subtitle(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()

    # Template file
    template = tmp_path / "overlay.ass"
    template.write_text("Team: {{home_team}} vs {{away_team}}", encoding="utf-8")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="Roseville",
            away_team="Mahtomedi",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"speed": 0.5, "subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "overlay",
            "--game-dir",
            str(game_dir),
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_render_apply_with_event_context(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()

    template = tmp_path / "overlay.ass"
    template.write_text("Player: {{player}}", encoding="utf-8")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="A",
            away_team="B",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
        events=[
            GameEvent(
                id="ev123",
                clip="period-1/r1.mkv",
                segment_number=1,
                event_type="goal",
                player="Smith",
            ),
        ],
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.ffmpeg.probe_duration", return_value=10.0),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "overlay",
                "--game-dir",
                str(game_dir),
                "--event",
                "ev123",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output


def test_render_apply_game_dir_not_found_nonfatal(tmp_path: Path) -> None:
    """Bad game dir is non-fatal for apply (just skips context)."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    bad_dir = tmp_path / "nonexistent"
    cfg = _config_with_profile(tmp_path)
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--game-dir",
            str(bad_dir),
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Profile: slowmo" in result.output


def test_render_apply_subtitle_cleanup_after_render(tmp_path: Path) -> None:
    """Rendered subtitle temp files are cleaned up after render."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    template = tmp_path / "overlay.ass"
    template.write_text("Hello", encoding="utf-8")

    state = GameState(
        game_info=GameInfo(
            date="2026-02-28",
            home_team="A",
            away_team="B",
            sport="hockey",
        ),
        created_at="2026-02-28T12:00:00+00:00",
    )
    _write_game_state(game_dir, state)

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    mock_result = _mock_result(tmp_path)
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "overlay",
                "--game-dir",
                str(game_dir),
                "--output",
                str(out_dir / "out.mp4"),
                "--config",
                str(cfg),
            ],
        )

    assert result.exit_code == 0
    # Temp .ass files should be cleaned up
    ass_files = list(out_dir.glob("*.ass"))
    assert ass_files == []


def test_render_apply_invalid_speed(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, speed=5.0)
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 1
    assert "Speed must be" in result.output


# ---------------------------------------------------------------------------
# --iterate on render apply
# ---------------------------------------------------------------------------


def _config_with_iterations(tmp_path: Path) -> Path:
    """Write a config file with profiles + iterations."""
    cfg_data = {
        "render_profiles": {
            "fullspeed": {"speed": 1.0},
            "slowmo": {"speed": 0.5},
        },
        "iterations": {
            "default": ["fullspeed", "slowmo"],
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))
    return cfg


def test_render_apply_iterate_dry_run(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Dry run — no files written", "Iterations: 2 profile(s)"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--iterate",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Iterations: 2 profile(s)" in result.output


def test_render_apply_iterate_executes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--iterate",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_apply_iterate_no_profiles_falls_through(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    # Config with profiles but no iterations section
    cfg = _config_with_profile(tmp_path, "slowmo", speed=0.5)
    result = runner.invoke(
        app,
        [
            "render",
            "apply",
            str(clip),
            "--render-profile",
            "slowmo",
            "--iterate",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "No iteration profiles configured" in result.output
    # Falls through to single render
    assert "Dry run" in result.output


def test_render_apply_iterate_with_game_dir(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="t1",
    )
    _write_game_state(game_dir, state)
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--iterate",
                "--game-dir",
                str(game_dir),
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_apply_iterate_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    from reeln.core.errors import RenderError

    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            side_effect=RenderError("iteration failed"),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--iterate",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 1
    assert "iteration failed" in result.output


# ---------------------------------------------------------------------------
# --iterate on render short / render preview
# ---------------------------------------------------------------------------


def test_render_short_iterate_dry_run(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Dry run — no files written", "Iterations: 2 profile(s)"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--config",
                str(cfg),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Iterations: 2 profile(s)" in result.output


def test_render_short_iterate_no_profiles(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_profile(tmp_path, "slowmo", speed=0.5)
    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--iterate",
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "No iteration profiles configured" in result.output


def test_render_short_iterate_executes(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_short_iterate_with_game_dir(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="t1",
        events=[
            GameEvent(
                id="ev1",
                clip="period-1/clip.mkv",
                segment_number=1,
                event_type="goal",
                created_at="t1",
            )
        ],
    )
    _write_game_state(game_dir, state)
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--game-dir",
                str(game_dir),
                "--event",
                "ev1",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_preview_iterate(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "preview",
                str(clip),
                "--iterate",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_short_iterate_game_dir_no_event(tmp_path: Path) -> None:
    """Iterate with --game-dir but no --event (event_id is None)."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26",
            home_team="a",
            away_team="b",
            sport="hockey",
        ),
        created_at="t1",
    )
    _write_game_state(game_dir, state)
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--game-dir",
                str(game_dir),
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_short_iterate_game_dir_load_fails(tmp_path: Path) -> None:
    """Iterate with --game-dir pointing to invalid dir — load_game_state fails gracefully."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    # No game.json → load_game_state will raise MediaError
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--game-dir",
                str(game_dir),
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_render_short_iterate_error(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    cfg = _config_with_iterations(tmp_path)
    from reeln.core.errors import RenderError

    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            side_effect=RenderError("iteration failed"),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 1
    assert "iteration failed" in result.output


# ---------------------------------------------------------------------------
# --debug flag
# ---------------------------------------------------------------------------


def test_render_short_debug(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    state = GameState(game_info=gi)
    _write_game_state(game_dir, state)

    mock_result = RenderResult(
        output=tmp_path / "out.mp4",
        duration_seconds=30.0,
        file_size_bytes=1024000,
        ffmpeg_command=["ffmpeg", "-i", str(clip), str(tmp_path / "out.mp4")],
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
        patch("reeln.core.ffmpeg.probe_duration", return_value=None),
        patch("reeln.core.ffmpeg.probe_fps", return_value=None),
        patch("reeln.core.ffmpeg.probe_resolution", return_value=None),
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--game-dir",
                str(game_dir),
                "--debug",
            ],
        )

    assert result.exit_code == 0
    assert "Debug:" in result.output
    assert (game_dir / "debug").is_dir()


def test_render_short_debug_no_game_dir(tmp_path: Path) -> None:
    """Debug with no game dir doesn't crash — debug is silently skipped."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    mock_result = RenderResult(
        output=tmp_path / "out.mp4",
        duration_seconds=30.0,
        file_size_bytes=1024000,
        ffmpeg_command=["ffmpeg", "-i", str(clip), str(tmp_path / "out.mp4")],
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
        patch("reeln.commands.render._find_game_dir", return_value=None),
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--debug",
            ],
        )

    assert result.exit_code == 0
    # No Debug line because there's no game dir to resolve to
    assert "Debug:" not in result.output


def test_render_preview_debug(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    state = GameState(game_info=gi)
    _write_game_state(game_dir, state)

    mock_result = RenderResult(
        output=tmp_path / "out.mp4",
        duration_seconds=10.0,
        file_size_bytes=512000,
        ffmpeg_command=["ffmpeg", "-i", str(clip), str(tmp_path / "out.mp4")],
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
        patch("reeln.core.ffmpeg.probe_duration", return_value=None),
        patch("reeln.core.ffmpeg.probe_fps", return_value=None),
        patch("reeln.core.ffmpeg.probe_resolution", return_value=None),
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "preview",
                str(clip),
                "--game-dir",
                str(game_dir),
                "--debug",
            ],
        )

    assert result.exit_code == 0
    assert "Debug:" in result.output


def test_render_apply_debug(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    state = GameState(game_info=gi)
    _write_game_state(game_dir, state)

    # Create config with a render profile
    cfg_data = {
        "config_version": 1,
        "render_profiles": {"slowmo": {"speed": 0.5}},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg_data))

    mock_result = RenderResult(
        output=tmp_path / "out.mp4",
        duration_seconds=60.0,
        file_size_bytes=2048000,
        ffmpeg_command=["ffmpeg", "-i", str(clip), str(tmp_path / "out.mp4")],
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
        patch("reeln.core.ffmpeg.probe_duration", return_value=None),
        patch("reeln.core.ffmpeg.probe_fps", return_value=None),
        patch("reeln.core.ffmpeg.probe_resolution", return_value=None),
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--game-dir",
                str(game_dir),
                "--debug",
                "--config",
                str(cfg_path),
            ],
        )

    assert result.exit_code == 0
    assert "Debug:" in result.output
    assert (game_dir / "debug").is_dir()


def test_render_apply_debug_no_game_dir(tmp_path: Path) -> None:
    """--debug without --game-dir is silently skipped."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    cfg_data = {
        "config_version": 1,
        "render_profiles": {"slowmo": {"speed": 0.5}},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg_data))

    mock_result = RenderResult(
        output=tmp_path / "out.mp4",
        duration_seconds=60.0,
        file_size_bytes=2048000,
        ffmpeg_command=["ffmpeg", "-i", str(clip), str(tmp_path / "out.mp4")],
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_cls,
    ):
        mock_cls.return_value.render.return_value = mock_result
        result = runner.invoke(
            app,
            [
                "render",
                "apply",
                str(clip),
                "--render-profile",
                "slowmo",
                "--debug",
                "--config",
                str(cfg_path),
            ],
        )

    assert result.exit_code == 0
    assert "Debug:" not in result.output


# ---------------------------------------------------------------------------
# --player / --assists with iterate path
# ---------------------------------------------------------------------------


def test_short_iterate_with_player_and_assists(tmp_path: Path) -> None:
    """--player and --assists flow through to iterate path context."""
    clip = tmp_path / "clip.mkv"
    clip.touch()
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    state = GameState(
        game_info=GameInfo(
            date="2026-02-26", home_team="A", away_team="B", sport="hockey"
        ),
        created_at="t1",
        events=[
            GameEvent(
                id="ev1", clip="clip.mkv", segment_number=1,
                event_type="goal", created_at="t1",
            ),
        ],
    )
    _write_game_state(game_dir, state)
    cfg = _config_with_iterations(tmp_path)
    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )
    with (
        patch("reeln.core.ffmpeg.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.iterations.render_iterations",
            return_value=(iter_result, ["Iteration rendering complete"]),
        ) as mock_iter,
    ):
        result = runner.invoke(
            app,
            [
                "render",
                "short",
                str(clip),
                "--iterate",
                "--game-dir",
                str(game_dir),
                "--event",
                "ev1",
                "--player",
                "NewPlayer",
                "--assists",
                "#22 Jones",
                "--config",
                str(cfg),
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output
    # Verify player override was passed to render_iterations
    call_kwargs = mock_iter.call_args
    ctx = call_kwargs.kwargs.get("context") or call_kwargs[1].get("context")
    assert ctx is not None
    assert ctx.get("player") == "NewPlayer"
    meta = call_kwargs.kwargs.get("event_metadata") or call_kwargs[1].get("event_metadata")
    assert meta is not None
    assert meta["assists"] == "#22 Jones"


def test_short_subtitle_game_dir_load_fails_nonfatal(tmp_path: Path) -> None:
    """Subtitle resolution handles game_dir load failure gracefully."""
    clip = tmp_path / "clip.mkv"
    clip.touch()

    template = tmp_path / "overlay.ass"
    template.write_text("Static overlay", encoding="utf-8")

    bad_game_dir = tmp_path / "badgame"
    bad_game_dir.mkdir()
    # Write invalid game.json to trigger ReelnError
    (bad_game_dir / "game.json").write_text("not json!")

    cfg_data = {
        "render_profiles": {
            "overlay": {"subtitle_template": str(template)},
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(cfg_data))

    result = runner.invoke(
        app,
        [
            "render",
            "short",
            str(clip),
            "--render-profile",
            "overlay",
            "--game-dir",
            str(bad_game_dir),
            "--config",
            str(cfg),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Subtitle:" in result.output
