"""Tests for the game command group."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from reeln.cli import app
from reeln.commands.game import _resolve_game_dir, _resolve_output_dir
from reeln.core.errors import ConfigError, MediaError, PromptAborted, ReelnError
from reeln.models.config import AppConfig, PathConfig
from reeln.models.game import GameState
from reeln.models.profile import IterationConfig, RenderProfile
from reeln.models.render_plan import CompilationResult, HighlightsResult, IterationResult, PruneResult, SegmentResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# _resolve_output_dir
# ---------------------------------------------------------------------------


def test_resolve_output_dir_cli_flag(tmp_path: Path) -> None:
    result = _resolve_output_dir(tmp_path / "cli", tmp_path / "config")
    assert result == tmp_path / "cli"


def test_resolve_output_dir_config_fallback(tmp_path: Path) -> None:
    result = _resolve_output_dir(None, tmp_path / "config")
    assert result == tmp_path / "config"


def test_resolve_output_dir_cwd_fallback() -> None:
    result = _resolve_output_dir(None, None)
    assert result == Path.cwd()


# ---------------------------------------------------------------------------
# _resolve_game_dir
# ---------------------------------------------------------------------------


def test_resolve_game_dir_direct(tmp_path: Path) -> None:
    """When the resolved path has game.json, use it directly."""
    (tmp_path / "game.json").write_text("{}")
    result = _resolve_game_dir(tmp_path, None)
    assert result == tmp_path


def test_resolve_game_dir_discovers_latest(tmp_path: Path) -> None:
    """When resolved path is the parent, discover the latest game dir."""
    import time

    old_game = tmp_path / "2026-01-01_a_vs_b"
    old_game.mkdir()
    (old_game / "game.json").write_text("{}")
    time.sleep(0.05)

    new_game = tmp_path / "2026-02-28_c_vs_d"
    new_game.mkdir()
    (new_game / "game.json").write_text("{}")

    result = _resolve_game_dir(tmp_path, None)
    assert result == new_game


def test_resolve_game_dir_no_games(tmp_path: Path) -> None:
    """Error when no game directories found."""
    result = runner.invoke(app, ["game", "segment", "1", "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "No game directory found" in result.output


def test_resolve_game_dir_skips_non_game_dirs(tmp_path: Path) -> None:
    """Directories without game.json are skipped."""
    (tmp_path / "random_dir").mkdir()
    game = tmp_path / "2026-02-28_a_vs_b"
    game.mkdir()
    (game / "game.json").write_text("{}")

    result = _resolve_game_dir(tmp_path, None)
    assert result == game


def test_resolve_game_dir_uses_config_output_dir(tmp_path: Path) -> None:
    """Falls through to config output_dir for discovery."""
    game = tmp_path / "2026-02-28_a_vs_b"
    game.mkdir()
    (game / "game.json").write_text("{}")

    result = _resolve_game_dir(None, tmp_path)
    assert result == game


def test_game_help_lists_commands() -> None:
    result = runner.invoke(app, ["game", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "segment" in result.output
    assert "highlights" in result.output
    assert "compile" in result.output
    assert "finish" in result.output
    assert "prune" in result.output


# ---------------------------------------------------------------------------
# game init
# ---------------------------------------------------------------------------


def test_game_init_creates_directory(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["game", "init", "roseville", "mahtomedi", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Game directory:" in result.output

    game_dir = tmp_path / f"{_today()}_roseville_vs_mahtomedi"
    assert game_dir.is_dir()
    assert (game_dir / "game.json").is_file()


def test_game_init_hockey_periods(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["game", "init", "a", "b", "-s", "hockey", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0

    game_dir = tmp_path / f"{_today()}_a_vs_b"
    assert (game_dir / "period-1").is_dir()
    assert (game_dir / "period-2").is_dir()
    assert (game_dir / "period-3").is_dir()


def test_game_init_basketball_quarters(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["game", "init", "lakers", "celtics", "-s", "basketball", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0

    game_dir = tmp_path / f"{_today()}_lakers_vs_celtics"
    assert (game_dir / "quarter-1").is_dir()
    assert (game_dir / "quarter-2").is_dir()
    assert (game_dir / "quarter-3").is_dir()
    assert (game_dir / "quarter-4").is_dir()


def test_game_init_dry_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["game", "init", "a", "b", "--dry-run", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    # No files or directories created
    assert list(tmp_path.iterdir()) == []


def test_game_init_custom_date(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["game", "init", "a", "b", "--date", "2026-12-25", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0

    game_dir = tmp_path / "2026-12-25_a_vs_b"
    assert game_dir.is_dir()


def test_game_init_double_header(tmp_path: Path) -> None:
    # First game
    result1 = runner.invoke(
        app,
        ["game", "init", "a", "b", "-s", "hockey", "-o", str(tmp_path)],
    )
    assert result1.exit_code == 0

    # Second game — auto-detects double-header
    result2 = runner.invoke(
        app,
        ["game", "init", "a", "b", "-s", "hockey", "-o", str(tmp_path)],
    )
    assert result2.exit_code == 0

    game_dir2 = tmp_path / f"{_today()}_a_vs_b_g2"
    assert game_dir2.is_dir()


def test_game_init_invalid_sport(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["game", "init", "a", "b", "-s", "quidditch", "-o", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_init_with_venue(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "game",
            "init",
            "a",
            "b",
            "-s",
            "hockey",
            "--venue",
            "OVAL",
            "-o",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0

    game_dir = tmp_path / f"{_today()}_a_vs_b"
    state = json.loads((game_dir / "game.json").read_text(encoding="utf-8"))
    assert state["game_info"]["venue"] == "OVAL"


def test_game_init_uses_config_output_dir(tmp_path: Path) -> None:
    """When -o is not passed, game init uses paths.output_dir from config."""
    cfg = AppConfig(paths=PathConfig(output_dir=tmp_path))
    with patch("reeln.commands.game.load_config", return_value=cfg):
        result = runner.invoke(
            app,
            ["game", "init", "a", "b"],
        )

    assert result.exit_code == 0
    game_dir = tmp_path / f"{_today()}_a_vs_b"
    assert game_dir.is_dir()


def test_game_init_config_error_exits() -> None:
    with patch(
        "reeln.commands.game.load_config",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(app, ["game", "init", "a", "b"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "bad config" in result.output


def test_game_init_help_shows_arguments() -> None:
    result = runner.invoke(app, ["game", "init", "--help"])
    assert result.exit_code == 0
    assert "HOME" in result.output
    assert "AWAY" in result.output
    assert "--sport" in result.output
    assert "--dry-run" in result.output
    assert "--profile" in result.output
    assert "--config" in result.output
    assert "--game-time" in result.output
    assert "--level" in result.output
    assert "--period-length" in result.output


# ---------------------------------------------------------------------------
# game init — interactive mode
# ---------------------------------------------------------------------------


def _mock_collect(**overrides: object) -> dict[str, object]:
    """Build a default interactive result dict with optional overrides."""
    defaults: dict[str, object] = {
        "home": "eagles",
        "away": "bears",
        "sport": "hockey",
        "game_date": _today(),
        "venue": "",
        "game_time": "",
        "period_length": 0,
        "description": "",
        "thumbnail": "",
        "home_profile": None,
        "away_profile": None,
    }
    defaults.update(overrides)
    return defaults


def test_game_init_no_args_triggers_interactive(tmp_path: Path) -> None:
    result_dict = _mock_collect()
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ) as mock_collect:
        result = runner.invoke(app, ["game", "init", "-o", str(tmp_path)])

    assert result.exit_code == 0
    mock_collect.assert_called_once()
    game_dir = tmp_path / f"{_today()}_eagles_vs_bears"
    assert game_dir.is_dir()


def test_game_init_home_only_triggers_interactive(tmp_path: Path) -> None:
    result_dict = _mock_collect(home="roseville")
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ) as mock_collect:
        result = runner.invoke(app, ["game", "init", "roseville", "-o", str(tmp_path)])

    assert result.exit_code == 0
    # home was passed as CLI arg, away was None → interactive mode triggered
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["home"] == "roseville"
    assert call_kwargs["away"] is None


def test_game_init_interactive_creates_directory_with_sport(tmp_path: Path) -> None:
    result_dict = _mock_collect(sport="basketball")
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ):
        result = runner.invoke(app, ["game", "init", "-o", str(tmp_path)])

    assert result.exit_code == 0
    game_dir = tmp_path / f"{_today()}_eagles_vs_bears"
    assert (game_dir / "quarter-1").is_dir()


def test_game_init_interactive_abort_exits() -> None:
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        side_effect=PromptAborted("cancelled"),
    ):
        result = runner.invoke(app, ["game", "init"])

    assert result.exit_code == 1
    assert "Aborted" in result.output


def test_game_init_interactive_dry_run(tmp_path: Path) -> None:
    result_dict = _mock_collect()
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ):
        result = runner.invoke(app, ["game", "init", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert list(tmp_path.iterdir()) == []


def test_game_init_interactive_passes_sport_preset(tmp_path: Path) -> None:
    """When --sport is explicitly set (not default), it's passed as preset."""
    result_dict = _mock_collect(sport="basketball")
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ) as mock_collect:
        result = runner.invoke(app, ["game", "init", "-s", "basketball", "-o", str(tmp_path)])

    assert result.exit_code == 0
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["sport"] == "basketball"


def test_game_init_interactive_missing_questionary() -> None:
    """ReelnError from missing dependency shows clean error, not traceback."""
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        side_effect=ReelnError("Interactive prompts require the 'questionary' package."),
    ):
        result = runner.invoke(app, ["game", "init"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "questionary" in result.output


def test_game_init_interactive_passes_venue_preset(tmp_path: Path) -> None:
    """When --venue is set, it's passed as preset (not None)."""
    result_dict = _mock_collect(venue="OVAL")
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ) as mock_collect:
        result = runner.invoke(app, ["game", "init", "--venue", "OVAL", "-o", str(tmp_path)])

    assert result.exit_code == 0
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["venue"] == "OVAL"


def test_game_init_interactive_passes_game_time_preset(tmp_path: Path) -> None:
    """When --game-time is set, it's passed as preset (not None)."""
    result_dict = _mock_collect(game_time="7:00 PM")
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ) as mock_collect:
        result = runner.invoke(app, ["game", "init", "--game-time", "7:00 PM", "-o", str(tmp_path)])

    assert result.exit_code == 0
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["game_time"] == "7:00 PM"


def test_game_init_interactive_passes_profiles_to_init(tmp_path: Path) -> None:
    """Interactive mode: profiles from collect are passed to init_game()."""
    from reeln.models.team import TeamProfile

    home_prof = TeamProfile(team_name="Eagles", short_name="EGL", level="bantam")
    away_prof = TeamProfile(team_name="Bears", short_name="BRS", level="bantam")
    result_dict = _mock_collect(
        home="Eagles",
        away="Bears",
        home_profile=home_prof,
        away_profile=away_prof,
    )
    with (
        patch(
            "reeln.commands.game.collect_game_info_interactive",
            return_value=result_dict,
        ),
        patch("reeln.commands.game.init_game", return_value=(tmp_path, [])) as mock_init,
    ):
        result = runner.invoke(app, ["game", "init", "-o", str(tmp_path)])

    assert result.exit_code == 0
    call_kwargs = mock_init.call_args
    assert call_kwargs.kwargs["home_profile"] is home_prof
    assert call_kwargs.kwargs["away_profile"] is away_prof


def test_game_init_with_game_time(tmp_path: Path) -> None:
    """Non-interactive mode: --game-time is stored in game.json."""
    result = runner.invoke(
        app,
        ["game", "init", "a", "b", "--game-time", "7:00 PM", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0

    game_dir = tmp_path / f"{_today()}_a_vs_b"
    state = json.loads((game_dir / "game.json").read_text(encoding="utf-8"))
    assert state["game_info"]["game_time"] == "7:00 PM"


def test_game_init_with_level_resolves_profiles(tmp_path: Path) -> None:
    """Non-interactive mode: --level resolves team slugs to profile names."""
    from reeln.models.team import TeamProfile

    home_profile = TeamProfile(team_name="Roseville", short_name="ROS", level="bantam")
    away_profile = TeamProfile(team_name="Mahtomedi", short_name="MAH", level="bantam")

    with patch("reeln.core.teams.load_team_profile") as mock_load:
        mock_load.side_effect = [home_profile, away_profile]
        result = runner.invoke(
            app,
            ["game", "init", "roseville", "mahtomedi", "--level", "bantam", "-o", str(tmp_path)],
        )

    assert result.exit_code == 0
    game_dir = tmp_path / f"{_today()}_Roseville_vs_Mahtomedi"
    assert game_dir.is_dir()


def test_game_init_with_level_missing_profile(tmp_path: Path) -> None:
    """Non-interactive mode: --level with unknown slug raises error."""
    with patch(
        "reeln.core.teams.load_team_profile",
        side_effect=ConfigError("Team profile not found: bantam/unknown"),
    ):
        result = runner.invoke(
            app,
            ["game", "init", "unknown", "mahtomedi", "--level", "bantam", "-o", str(tmp_path)],
        )

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "not found" in result.output


def test_game_init_with_period_length(tmp_path: Path) -> None:
    """Non-interactive mode: --period-length is stored in game.json."""
    result = runner.invoke(
        app,
        ["game", "init", "a", "b", "--period-length", "12", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0

    game_dir = tmp_path / f"{_today()}_a_vs_b"
    state = json.loads((game_dir / "game.json").read_text(encoding="utf-8"))
    assert state["game_info"]["period_length"] == 12


def test_game_init_interactive_passes_period_length_preset(tmp_path: Path) -> None:
    """When --period-length is set, it's passed as preset (not None)."""
    result_dict = _mock_collect(period_length=12)
    with patch(
        "reeln.commands.game.collect_game_info_interactive",
        return_value=result_dict,
    ) as mock_collect:
        result = runner.invoke(
            app, ["game", "init", "--period-length", "12", "-o", str(tmp_path)]
        )

    assert result.exit_code == 0
    call_kwargs = mock_collect.call_args.kwargs
    assert call_kwargs["period_length"] == 12


# ---------------------------------------------------------------------------
# game segment
# ---------------------------------------------------------------------------


def _mock_segment_result(tmp_path: Path) -> SegmentResult:
    return SegmentResult(
        segment_number=1,
        segment_dir=tmp_path / "period-1",
        input_files=[tmp_path / "replay1.mkv"],
        output=tmp_path / "period-1_2026-02-26.mkv",
        copy=True,
    )


def _mock_load_config() -> AppConfig:
    return AppConfig()


def test_game_segment_merges_files(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Segment: period-1", "Merge complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.process_segment",
            return_value=(result_obj, messages),
        ),
    ):
        result = runner.invoke(app, ["game", "segment", "1", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Segment: period-1" in result.output
    assert "Merge complete" in result.output


def test_game_segment_passes_video_config(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Segment: period-1", "Merge complete"]
    config = _mock_load_config()
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.process_segment",
            return_value=(result_obj, messages),
        ) as mock_ps,
    ):
        runner.invoke(app, ["game", "segment", "1", "-o", str(tmp_path)])

    call_kwargs = mock_ps.call_args.kwargs
    assert call_kwargs["video_config"] is config.video


def test_game_segment_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Dry run — no files written", "Segment: period-1"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.process_segment",
            return_value=(result_obj, messages),
        ) as mock_ps,
    ):
        result = runner.invoke(app, ["game", "segment", "1", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Dry run" in result.output
    call_kwargs = mock_ps.call_args.kwargs
    assert call_kwargs["dry_run"] is True


def test_game_segment_error_exits(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.process_segment",
            side_effect=MediaError("No video files found"),
        ),
    ):
        result = runner.invoke(app, ["game", "segment", "1", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_segment_uses_config_output_dir(tmp_path: Path) -> None:
    """When -o is not passed, game segment discovers latest game in config output_dir."""
    game = tmp_path / "2026-02-28_a_vs_b"
    game.mkdir()
    (game / "game.json").write_text("{}")
    cfg = AppConfig(paths=PathConfig(output_dir=tmp_path))
    result_obj = _mock_segment_result(game)
    messages = ["Segment: period-1"]
    with (
        patch("reeln.commands.game.load_config", return_value=cfg),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.process_segment",
            return_value=(result_obj, messages),
        ) as mock_ps,
    ):
        result = runner.invoke(app, ["game", "segment", "1"])

    assert result.exit_code == 0
    call_args = mock_ps.call_args
    assert call_args[0][0] == game  # game_dir resolved via discovery


def test_game_segment_config_error_exits() -> None:
    with patch(
        "reeln.commands.game.load_config",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(app, ["game", "segment", "1"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "bad config" in result.output


def test_game_segment_ffmpeg_not_found(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.commands.game.discover_ffmpeg",
            side_effect=FFmpegError("ffmpeg not found"),
        ),
    ):
        result = runner.invoke(app, ["game", "segment", "1", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_segment_help_shows_options() -> None:
    result = runner.invoke(app, ["game", "segment", "--help"])
    assert result.exit_code == 0
    assert "NUMBER" in result.output
    assert "--dry-run" in result.output
    assert "--output-dir" in result.output
    assert "--profile" in result.output
    assert "--config" in result.output
    assert "--render-profile" in result.output


def test_game_segment_with_render_profile(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    # Create the merge output so _apply_profile_post can find it
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Segment: period-1", "Merge complete"]
    config = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
    )
    from reeln.models.render_plan import RenderResult

    def _fake_render(plan: object) -> RenderResult:
        # Create the profiled temp file so replace() works
        assert hasattr(plan, "output")
        plan.output.write_bytes(b"profiled")  # type: ignore[union-attr]
        return RenderResult(output=plan.output)  # type: ignore[union-attr]

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_renderer,
    ):
        mock_renderer.return_value.render.side_effect = _fake_render
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
            ],
        )
    assert result.exit_code == 0
    assert "Profile 'slowmo' applied" in result.output


def test_game_segment_render_profile_unknown(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Merge complete"]
    config = AppConfig()
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--render-profile",
                "nonexistent",
            ],
        )
    assert result.exit_code == 0  # non-fatal warning
    assert "Warning:" in result.output


def test_game_segment_render_profile_plan_error(tmp_path: Path) -> None:
    """plan_full_frame failure is non-fatal — warning emitted."""
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Merge complete"]
    config = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
    )
    from reeln.core.errors import RenderError

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch(
            "reeln.core.profiles.plan_full_frame",
            side_effect=RenderError("invalid speed"),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
            ],
        )
    assert result.exit_code == 0
    assert "Profile plan error" in result.output


def test_game_segment_render_profile_render_failure(tmp_path: Path) -> None:
    """FFmpegRenderer.render failure is non-fatal — temp file cleaned up."""
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Merge complete"]
    config = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
    )
    from reeln.core.errors import RenderError

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_renderer,
    ):
        mock_renderer.return_value.render.side_effect = RenderError("encode failed")
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
            ],
        )
    assert result.exit_code == 0
    assert "Profile render failed" in result.output


def test_game_segment_render_profile_skipped_on_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Dry run — no files written"]
    config = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
    )
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Profile" not in result.output


# ---------------------------------------------------------------------------
# game highlights
# ---------------------------------------------------------------------------


def _mock_highlights_result(tmp_path: Path) -> HighlightsResult:
    return HighlightsResult(
        output=tmp_path / "roseville_vs_mahtomedi_2026-02-26.mkv",
        segment_files=[tmp_path / f"period-{i}_2026-02-26.mkv" for i in range(1, 4)],
        copy=True,
    )


def test_game_highlights_merges(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Sport: hockey", "Highlights merge complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.merge_game_highlights",
            return_value=(result_obj, messages),
        ),
    ):
        result = runner.invoke(app, ["game", "highlights", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Highlights merge complete" in result.output


def test_game_highlights_passes_video_config(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Sport: hockey", "Highlights merge complete"]
    config = _mock_load_config()
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.merge_game_highlights",
            return_value=(result_obj, messages),
        ) as mock_mgh,
    ):
        runner.invoke(app, ["game", "highlights", "-o", str(tmp_path)])

    call_kwargs = mock_mgh.call_args.kwargs
    assert call_kwargs["video_config"] is config.video


def test_game_highlights_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Dry run — no files written", "Sport: hockey"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.merge_game_highlights",
            return_value=(result_obj, messages),
        ) as mock_mgh,
    ):
        result = runner.invoke(app, ["game", "highlights", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Dry run" in result.output
    call_kwargs = mock_mgh.call_args.kwargs
    assert call_kwargs["dry_run"] is True


def test_game_highlights_error_exits(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.merge_game_highlights",
            side_effect=MediaError("No segment highlight files found"),
        ),
    ):
        result = runner.invoke(app, ["game", "highlights", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_highlights_uses_config_output_dir(tmp_path: Path) -> None:
    """When -o is not passed, game highlights discovers latest game in config output_dir."""
    game = tmp_path / "2026-02-28_a_vs_b"
    game.mkdir()
    (game / "game.json").write_text("{}")
    cfg = AppConfig(paths=PathConfig(output_dir=tmp_path))
    result_obj = _mock_highlights_result(game)
    messages = ["Highlights merge complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=cfg),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.commands.game.merge_game_highlights",
            return_value=(result_obj, messages),
        ) as mock_mgh,
    ):
        result = runner.invoke(app, ["game", "highlights"])

    assert result.exit_code == 0
    call_args = mock_mgh.call_args
    assert call_args[0][0] == game  # game_dir resolved via discovery


def test_game_highlights_config_error_exits() -> None:
    with patch(
        "reeln.commands.game.load_config",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(app, ["game", "highlights"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "bad config" in result.output


def test_game_highlights_ffmpeg_not_found(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.commands.game.discover_ffmpeg",
            side_effect=FFmpegError("ffmpeg not found"),
        ),
    ):
        result = runner.invoke(app, ["game", "highlights", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_highlights_help_shows_options() -> None:
    result = runner.invoke(app, ["game", "highlights", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--output-dir" in result.output
    assert "--profile" in result.output
    assert "--config" in result.output
    assert "--render-profile" in result.output


def test_game_highlights_with_render_profile(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    # Create the merge output so _apply_profile_post can find it
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Highlights merge complete"]
    config = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
    )
    from reeln.models.render_plan import RenderResult

    def _fake_render(plan: object) -> RenderResult:
        assert hasattr(plan, "output")
        plan.output.write_bytes(b"profiled")  # type: ignore[union-attr]
        return RenderResult(output=plan.output)  # type: ignore[union-attr]

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_renderer,
    ):
        mock_renderer.return_value.render.side_effect = _fake_render
        result = runner.invoke(
            app,
            [
                "game",
                "highlights",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
            ],
        )
    assert result.exit_code == 0
    assert "Profile 'slowmo' applied" in result.output


def test_game_highlights_render_profile_unknown(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Highlights merge complete"]
    config = AppConfig()
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "highlights",
                "-o",
                str(tmp_path),
                "--render-profile",
                "nonexistent",
            ],
        )
    assert result.exit_code == 0  # non-fatal warning
    assert "Warning:" in result.output


def test_game_highlights_render_profile_skipped_on_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Dry run — no files written"]
    config = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
    )
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "highlights",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Profile" not in result.output


# ---------------------------------------------------------------------------
# game compile
# ---------------------------------------------------------------------------


def _mock_compilation_result(tmp_path: Path) -> CompilationResult:
    return CompilationResult(
        output=tmp_path / "a_vs_b_2026-02-28_all_compilation.mkv",
        event_ids=["aaa111", "bbb222"],
        input_files=[tmp_path / "period-1/r1.mkv", tmp_path / "period-1/r2.mkv"],
        copy=True,
    )


def test_game_compile_basic(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Events: 2", "Compilation complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ),
    ):
        result = runner.invoke(app, ["game", "compile", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Events: 2" in result.output
    assert "Compilation complete" in result.output


def test_game_compile_with_type_filter(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Events: 2"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ) as mock_ce,
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "compile",
                "--type",
                "goal",
                "-o",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    call_kwargs = mock_ce.call_args.kwargs
    assert call_kwargs["event_type"] == "goal"


def test_game_compile_with_segment_filter(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Events: 2"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ) as mock_ce,
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "compile",
                "--segment",
                "1",
                "-o",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    call_kwargs = mock_ce.call_args.kwargs
    assert call_kwargs["segment_number"] == 1


def test_game_compile_with_player_filter(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Events: 2"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ) as mock_ce,
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "compile",
                "--player",
                "#17",
                "-o",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    call_kwargs = mock_ce.call_args.kwargs
    assert call_kwargs["player"] == "#17"


def test_game_compile_with_output(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    out = tmp_path / "custom.mkv"
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Events: 2"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ) as mock_ce,
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "compile",
                "--output",
                str(out),
                "-o",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    call_kwargs = mock_ce.call_args.kwargs
    assert call_kwargs["output"] == out


def test_game_compile_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Dry run — no files written", "Events: 2"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ) as mock_ce,
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "compile",
                "--dry-run",
                "-o",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    assert "Dry run" in result.output
    call_kwargs = mock_ce.call_args.kwargs
    assert call_kwargs["dry_run"] is True


def test_game_compile_error_exits(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            side_effect=MediaError("No events match the given criteria"),
        ),
    ):
        result = runner.invoke(app, ["game", "compile", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_compile_config_error_exits() -> None:
    with patch(
        "reeln.commands.game.load_config",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(app, ["game", "compile"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "bad config" in result.output


def test_game_compile_ffmpeg_not_found(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.commands.game.discover_ffmpeg",
            side_effect=FFmpegError("ffmpeg not found"),
        ),
    ):
        result = runner.invoke(app, ["game", "compile", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_game_compile_passes_video_config(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Events: 2"]
    config = _mock_load_config()
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch(
            "reeln.core.events.compile_events",
            return_value=(result_obj, messages),
        ) as mock_ce,
    ):
        runner.invoke(app, ["game", "compile", "-o", str(tmp_path)])

    call_kwargs = mock_ce.call_args.kwargs
    assert call_kwargs["video_config"] is config.video


def test_game_compile_help_shows_options() -> None:
    result = runner.invoke(app, ["game", "compile", "--help"])
    assert result.exit_code == 0
    assert "--type" in result.output
    assert "--segment" in result.output
    assert "--player" in result.output
    assert "--output" in result.output
    assert "--dry-run" in result.output
    assert "--output-dir" in result.output


# ---------------------------------------------------------------------------
# game finish
# ---------------------------------------------------------------------------


def test_game_finish_basic(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    state = GameState.__new__(GameState)
    messages = ["Game: a vs b (2026-02-26)", "Status: Finished"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.finish.finish_game",
            return_value=(state, messages),
        ),
    ):
        result = runner.invoke(app, ["game", "finish", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Status: Finished" in result.output


def test_game_finish_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    state = GameState.__new__(GameState)
    messages = ["Game: a vs b (2026-02-26)", "Status: Finished"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.finish.finish_game",
            return_value=(state, messages),
        ) as mock_fg,
    ):
        result = runner.invoke(app, ["game", "finish", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    call_kwargs = mock_fg.call_args.kwargs
    assert call_kwargs["dry_run"] is True


def test_game_finish_already_finished(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.finish.finish_game",
            side_effect=MediaError("Game is already finished"),
        ),
    ):
        result = runner.invoke(app, ["game", "finish", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "already finished" in result.output


def test_game_finish_config_error_exits() -> None:
    with patch(
        "reeln.commands.game.load_config",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(app, ["game", "finish"])

    assert result.exit_code == 1
    assert "bad config" in result.output


def test_game_finish_help_shows_options() -> None:
    result = runner.invoke(app, ["game", "finish", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in result.output
    assert "--dry-run" in result.output
    assert "--profile" in result.output
    assert "--config" in result.output


# ---------------------------------------------------------------------------
# game prune
# ---------------------------------------------------------------------------


def test_game_prune_basic(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = PruneResult(removed_paths=[tmp_path / "highlight.mkv"], bytes_freed=1024)
    messages = ["Removed 1 file(s), 1.0 KB"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.prune.prune_game",
            return_value=(result_obj, messages),
        ),
    ):
        result = runner.invoke(app, ["game", "prune", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Removed 1 file(s)" in result.output


def test_game_prune_all_flag(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = PruneResult()
    messages = ["Nothing to prune"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.prune.prune_game",
            return_value=(result_obj, messages),
        ) as mock_pg,
    ):
        result = runner.invoke(app, ["game", "prune", "--all", "-o", str(tmp_path)])

    assert result.exit_code == 0
    call_kwargs = mock_pg.call_args.kwargs
    assert call_kwargs["all_files"] is True


def test_game_prune_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = PruneResult(removed_paths=[tmp_path / "highlight.mkv"], bytes_freed=100)
    messages = ["Would remove 1 file(s), 100 B"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.prune.prune_game",
            return_value=(result_obj, messages),
        ) as mock_pg,
    ):
        result = runner.invoke(app, ["game", "prune", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Would remove" in result.output
    call_kwargs = mock_pg.call_args.kwargs
    assert call_kwargs["dry_run"] is True


def test_game_prune_not_finished(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch(
            "reeln.core.prune.prune_game",
            side_effect=MediaError("Game must be finished before pruning"),
        ),
    ):
        result = runner.invoke(app, ["game", "prune", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "must be finished" in result.output


def test_game_prune_config_error_exits() -> None:
    with patch(
        "reeln.commands.game.load_config",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(app, ["game", "prune"])

    assert result.exit_code == 1
    assert "bad config" in result.output


def test_game_prune_help_shows_options() -> None:
    result = runner.invoke(app, ["game", "prune", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in result.output
    assert "--all" in result.output
    assert "--dry-run" in result.output
    assert "--profile" in result.output
    assert "--config" in result.output


# ---------------------------------------------------------------------------
# game segment --iterate
# ---------------------------------------------------------------------------


def _iteration_config() -> AppConfig:
    return AppConfig(
        render_profiles={
            "fullspeed": RenderProfile(name="fullspeed", speed=1.0),
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        },
        iterations=IterationConfig(mappings={"default": ["fullspeed", "slowmo"]}),
    )


def test_game_segment_iterate(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Merge complete"]
    config = _iteration_config()

    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )

    def _fake_iter(*args: object, **kwargs: object) -> tuple[IterationResult, list[str]]:
        # Create the temp output file that _apply_iterations_post expects
        temp = result_obj.output.with_stem(f"{result_obj.output.stem}_iterated")
        temp.write_bytes(b"iterated")
        return iter_result, ["Iteration rendering complete"]

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch("reeln.core.iterations.render_iterations", side_effect=_fake_iter),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--iterate",
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_game_segment_render_profile_overrides_iterate(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Merge complete"]
    config = _iteration_config()

    from reeln.models.render_plan import RenderResult

    def _fake_render(plan: object) -> RenderResult:
        assert hasattr(plan, "output")
        plan.output.write_bytes(b"profiled")  # type: ignore[union-attr]
        return RenderResult(output=plan.output)  # type: ignore[union-attr]

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_renderer,
    ):
        mock_renderer.return_value.render.side_effect = _fake_render
        # --render-profile takes precedence over --iterate
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
                "--iterate",
            ],
        )
    assert result.exit_code == 0
    assert "Profile 'slowmo' applied" in result.output


def test_game_segment_iterate_skipped_on_dry_run(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Dry run — no files written"]
    config = _iteration_config()
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--iterate",
                "--dry-run",
            ],
        )
    assert result.exit_code == 0
    assert "Dry run" in result.output


def test_game_segment_iterate_no_profiles(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Merge complete"]
    config = AppConfig()  # No iterations configured
    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--iterate",
            ],
        )
    assert result.exit_code == 0
    # No profiles → no iteration applied (silent)


def test_game_segment_iterate_failure_is_warning(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Merge complete"]
    config = _iteration_config()

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch(
            "reeln.core.iterations.render_iterations",
            side_effect=ReelnError("render exploded"),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "segment",
                "1",
                "-o",
                str(tmp_path),
                "--iterate",
            ],
        )
    assert result.exit_code == 0  # non-fatal
    assert "Warning" in result.output


# ---------------------------------------------------------------------------
# game highlights --iterate
# ---------------------------------------------------------------------------


def test_game_highlights_iterate(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Highlights merge complete"]
    config = _iteration_config()

    iter_result = IterationResult(
        output=tmp_path / "out.mp4",
        iteration_outputs=[],
        profile_names=["fullspeed", "slowmo"],
        concat_copy=True,
    )

    def _fake_iter(*args: object, **kwargs: object) -> tuple[IterationResult, list[str]]:
        temp = result_obj.output.with_stem(f"{result_obj.output.stem}_iterated")
        temp.write_bytes(b"iterated")
        return iter_result, ["Iteration rendering complete"]

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
        patch("reeln.core.iterations.render_iterations", side_effect=_fake_iter),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "highlights",
                "-o",
                str(tmp_path),
                "--iterate",
            ],
        )
    assert result.exit_code == 0
    assert "Iteration rendering complete" in result.output


def test_game_highlights_render_profile_overrides_iterate(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    result_obj.output.parent.mkdir(parents=True, exist_ok=True)
    result_obj.output.write_bytes(b"merged")
    messages = ["Highlights merge complete"]
    config = _iteration_config()

    from reeln.models.render_plan import RenderResult

    def _fake_render(plan: object) -> RenderResult:
        assert hasattr(plan, "output")
        plan.output.write_bytes(b"profiled")  # type: ignore[union-attr]
        return RenderResult(output=plan.output)  # type: ignore[union-attr]

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
        patch("reeln.core.renderer.FFmpegRenderer") as mock_renderer,
    ):
        mock_renderer.return_value.render.side_effect = _fake_render
        result = runner.invoke(
            app,
            [
                "game",
                "highlights",
                "-o",
                str(tmp_path),
                "--render-profile",
                "slowmo",
                "--iterate",
            ],
        )
    assert result.exit_code == 0
    assert "Profile 'slowmo' applied" in result.output


def test_game_highlights_iterate_no_profiles(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Highlights merge complete"]
    config = AppConfig()  # No iterations configured

    with (
        patch("reeln.commands.game.load_config", return_value=config),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(
            app,
            [
                "game",
                "highlights",
                "-o",
                str(tmp_path),
                "--iterate",
            ],
        )
    assert result.exit_code == 0
    # No profiles → no iteration applied (silent)


# ---------------------------------------------------------------------------
# --debug flag
# ---------------------------------------------------------------------------


def test_game_segment_debug(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = SegmentResult(
        segment_number=1,
        segment_dir=tmp_path / "period-1",
        input_files=[tmp_path / "replay1.mkv"],
        output=tmp_path / "period-1_2026-02-26.mkv",
        copy=True,
        ffmpeg_command=["ffmpeg", "-f", "concat", "-i", "list.txt", "out.mkv"],
    )
    messages = ["Segment: period-1", "Merge complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
        patch("reeln.core.ffmpeg.probe_duration", return_value=None),
        patch("reeln.core.ffmpeg.probe_fps", return_value=None),
        patch("reeln.core.ffmpeg.probe_resolution", return_value=None),
    ):
        result = runner.invoke(app, ["game", "segment", "1", "--debug", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Debug:" in result.output
    assert (tmp_path / "debug").is_dir()


def test_game_segment_debug_dry_run_skipped(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_segment_result(tmp_path)
    messages = ["Dry run — no files written"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.process_segment", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(app, ["game", "segment", "1", "--debug", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    # Debug is not written in dry-run (no ffmpeg_command)
    assert "Debug:" not in result.output


def test_game_highlights_debug(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = HighlightsResult(
        output=tmp_path / "roseville_vs_mahtomedi_2026-02-26.mkv",
        segment_files=[tmp_path / "period-1_2026-02-26.mkv"],
        copy=True,
        ffmpeg_command=["ffmpeg", "-f", "concat", "-i", "list.txt", "out.mkv"],
    )
    messages = ["Highlights merge complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
        patch("reeln.core.ffmpeg.probe_duration", return_value=None),
        patch("reeln.core.ffmpeg.probe_fps", return_value=None),
        patch("reeln.core.ffmpeg.probe_resolution", return_value=None),
    ):
        result = runner.invoke(app, ["game", "highlights", "--debug", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Debug:" in result.output
    assert (tmp_path / "debug").is_dir()


def test_game_highlights_debug_dry_run_skipped(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_highlights_result(tmp_path)
    messages = ["Dry run — no files written"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.commands.game.merge_game_highlights", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(app, ["game", "highlights", "--debug", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Debug:" not in result.output


def test_game_compile_debug(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = CompilationResult(
        output=tmp_path / "compilation.mkv",
        event_ids=["aaa111"],
        input_files=[tmp_path / "period-1" / "r1.mkv"],
        copy=True,
        ffmpeg_command=["ffmpeg", "-f", "concat", "-i", "list.txt", "out.mkv"],
    )
    messages = ["Events: 1", "Compilation complete"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.events.compile_events", return_value=(result_obj, messages)),
        patch("reeln.core.ffmpeg.probe_duration", return_value=None),
        patch("reeln.core.ffmpeg.probe_fps", return_value=None),
        patch("reeln.core.ffmpeg.probe_resolution", return_value=None),
    ):
        result = runner.invoke(app, ["game", "compile", "--debug", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Debug:" in result.output
    assert (tmp_path / "debug").is_dir()


def test_game_compile_debug_dry_run_skipped(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("{}")
    result_obj = _mock_compilation_result(tmp_path)
    messages = ["Dry run — no files written"]
    with (
        patch("reeln.commands.game.load_config", return_value=_mock_load_config()),
        patch("reeln.commands.game.discover_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("reeln.core.events.compile_events", return_value=(result_obj, messages)),
    ):
        result = runner.invoke(app, ["game", "compile", "--debug", "--dry-run", "-o", str(tmp_path)])

    assert result.exit_code == 0
    assert "Debug:" not in result.output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    from datetime import date

    return date.today().isoformat()
