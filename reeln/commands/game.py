"""Game command group: init, segment, highlights, finish, compile, event."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from reeln.commands import event
from reeln.core.config import load_config
from reeln.core.errors import PromptAborted, ReelnError
from reeln.core.ffmpeg import discover_ffmpeg
from reeln.core.highlights import init_game, merge_game_highlights, process_segment
from reeln.core.prompts import collect_game_info_interactive
from reeln.models.game import GameInfo
from reeln.plugins.loader import activate_plugins

app = typer.Typer(no_args_is_help=True, help="Game lifecycle commands.")
app.add_typer(event.app, name="event")


def _resolve_output_dir(output_dir: Path | None, config_output_dir: Path | None) -> Path:
    """Resolve output directory: CLI flag → config paths.output_dir → cwd."""
    if output_dir is not None:
        return output_dir
    if config_output_dir is not None:
        return config_output_dir
    return Path.cwd()


def _resolve_game_dir(output_dir: Path | None, config_output_dir: Path | None) -> Path:
    """Resolve game directory for segment/highlights commands.

    If the resolved directory contains ``game.json``, use it directly.
    Otherwise, search subdirectories for the most recently modified
    ``game.json`` and use its parent.
    """
    base = _resolve_output_dir(output_dir, config_output_dir)
    if (base / "game.json").is_file():
        return base
    # Search for latest game directory
    candidates = [f for f in base.iterdir() if f.is_dir() and (f / "game.json").is_file()]
    if not candidates:
        typer.echo(
            f"Error: No game directory found in {base}.\n"
            "Either cd into a game directory, pass -o <game-dir>, "
            "or set paths.output_dir in config.",
            err=True,
        )
        raise typer.Exit(code=1)
    return max(candidates, key=lambda p: (p / "game.json").stat().st_mtime)


def _apply_profile_post(
    merge_output: Path,
    profile_name: str,
    config: object,
    game_dir: Path,
    ffmpeg_path: Path,
) -> None:
    """Apply a render profile to the merge output as post-processing.

    Renders to a temp file, then replaces the original output.
    """
    from reeln.core.profiles import plan_full_frame, resolve_profile
    from reeln.core.renderer import FFmpegRenderer
    from reeln.models.config import AppConfig

    assert isinstance(config, AppConfig)

    try:
        rp = resolve_profile(config, profile_name)
    except ReelnError as exc:
        typer.echo(f"Warning: Profile error: {exc}", err=True)
        return

    temp_output = merge_output.with_stem(f"{merge_output.stem}_profiled")
    try:
        plan = plan_full_frame(merge_output, temp_output, rp, config)
    except ReelnError as exc:
        typer.echo(f"Warning: Profile plan error: {exc}", err=True)
        return

    try:
        renderer = FFmpegRenderer(ffmpeg_path)
        renderer.render(plan)
        temp_output.replace(merge_output)
        typer.echo(f"Profile '{profile_name}' applied")
    except ReelnError as exc:
        temp_output.unlink(missing_ok=True)
        typer.echo(f"Warning: Profile render failed: {exc}", err=True)


def _apply_iterations_post(
    merge_output: Path,
    profile_names: list[str],
    config: object,
    game_dir: Path,
    ffmpeg_path: Path,
) -> None:
    """Apply multi-iteration rendering to the merge output as post-processing.

    Renders to a temp file, then replaces the original output.
    """
    from reeln.core.iterations import render_iterations
    from reeln.models.config import AppConfig

    assert isinstance(config, AppConfig)

    temp_output = merge_output.with_stem(f"{merge_output.stem}_iterated")
    try:
        _, messages = render_iterations(
            merge_output,
            profile_names,
            config,
            ffmpeg_path,
            temp_output,
        )
    except ReelnError as exc:
        temp_output.unlink(missing_ok=True)
        typer.echo(f"Warning: Iteration render failed: {exc}", err=True)
        return

    temp_output.replace(merge_output)
    for msg in messages:
        typer.echo(msg)


@app.command()
def init(
    home: str | None = typer.Argument(None, help="Home team name."),
    away: str | None = typer.Argument(None, help="Away team name."),
    sport: str = typer.Option("generic", "--sport", "-s", help="Sport type."),
    game_date: str | None = typer.Option(None, "--date", help="Game date YYYY-MM-DD. Default: today."),
    venue: str = typer.Option("", "--venue", help="Venue name."),
    game_time: str = typer.Option("", "--game-time", "-t", help="Game time (e.g. '7:00 PM')."),
    level: str | None = typer.Option(None, "--level", "-l", help="Team level for profile lookup."),
    period_length: int = typer.Option(0, "--period-length", help="Period/segment length in minutes (0 = not set)."),
    description: str = typer.Option("", "--description", "-d", help="Broadcast description."),
    thumbnail: str = typer.Option("", "--thumbnail", help="Thumbnail image file path."),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Base output directory."),
    profile: str | None = typer.Option(None, "--profile", help="Named config profile."),
    config_path: Path | None = typer.Option(None, "--config", help="Explicit config file path."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without creating."),
) -> None:
    """Initialize a new game workspace."""
    try:
        config = load_config(path=config_path, profile=profile)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    activate_plugins(config.plugins)

    base = _resolve_output_dir(output_dir, config.paths.output_dir)

    home_profile = None
    away_profile = None

    if home is None or away is None:
        # Interactive mode — prompt for missing fields
        try:
            info = collect_game_info_interactive(
                home=home,
                away=away,
                sport=None if sport == "generic" else sport,
                game_date=game_date,
                venue=None if venue == "" else venue,
                game_time=None if game_time == "" else game_time,
                period_length=None if period_length == 0 else period_length,
                description=None if description == "" else description,
                thumbnail=None if thumbnail == "" else thumbnail,
            )
        except PromptAborted:
            raise typer.Abort() from None
        except ReelnError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        home_profile = info.get("home_profile")
        away_profile = info.get("away_profile")
        game_info = GameInfo(
            date=info["game_date"],
            home_team=info["home"],
            away_team=info["away"],
            sport=info["sport"],
            venue=info["venue"],
            game_time=info["game_time"],
            period_length=info["period_length"],
            description=info["description"],
            thumbnail=info["thumbnail"],
        )
    else:
        # Non-interactive mode — use CLI args directly
        resolved_date = game_date or date.today().isoformat()
        home_team = home
        away_team = away

        if level is not None:
            try:
                from reeln.core.teams import load_team_profile, slugify

                home_profile = load_team_profile(level, slugify(home))
                away_profile = load_team_profile(level, slugify(away))
                home_team = home_profile.team_name
                away_team = away_profile.team_name
            except ReelnError as exc:
                typer.echo(f"Error: {exc}", err=True)
                raise typer.Exit(code=1) from exc

        game_info = GameInfo(
            date=resolved_date,
            home_team=home_team,
            away_team=away_team,
            sport=sport,
            venue=venue,
            game_time=game_time,
            period_length=period_length,
            description=description,
            thumbnail=thumbnail,
        )

    try:
        _, messages = init_game(
            base, game_info, dry_run=dry_run, home_profile=home_profile, away_profile=away_profile
        )
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for msg in messages:
        typer.echo(msg)


@app.command()
def segment(
    number: int = typer.Argument(..., help="Segment number (1-indexed)."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Game directory (default: current directory)."
    ),
    render_profile: str | None = typer.Option(
        None, "--render-profile", "-r", help="Apply a named render profile after merge."
    ),
    iterate: bool = typer.Option(False, "--iterate", help="Multi-iteration mode using event type config."),
    profile: str | None = typer.Option(None, "--profile", help="Named config profile."),
    config_path: Path | None = typer.Option(None, "--config", help="Explicit config file path."),
    debug: bool = typer.Option(False, "--debug", help="Write debug artifacts to game debug directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without merging."),
) -> None:
    """Merge replays in a segment directory into a single highlight video."""
    try:
        config = load_config(path=config_path, profile=profile)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    activate_plugins(config.plugins)

    game_dir = _resolve_game_dir(output_dir, config.paths.output_dir)

    try:
        ffmpeg_path = discover_ffmpeg()
        result, messages = process_segment(
            game_dir,
            number,
            ffmpeg_path=ffmpeg_path,
            video_config=config.video,
            source_dir=config.paths.source_dir,
            source_glob=config.paths.source_glob,
            dry_run=dry_run,
        )
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for msg in messages:
        typer.echo(msg)

    if debug and not dry_run and result.ffmpeg_command:
        from reeln.core.debug import build_debug_artifact, write_debug_artifact, write_debug_index

        artifact = build_debug_artifact(
            "segment_merge",
            result.ffmpeg_command,
            result.input_files,
            result.output,
            game_dir,
            ffmpeg_path,
            extra={"segment_number": number, "copy": result.copy, "events_created": result.events_created},
        )
        write_debug_artifact(game_dir, artifact)
        write_debug_index(game_dir)
        typer.echo(f"Debug: {game_dir / 'debug'}")

    # --render-profile takes precedence over --iterate
    if render_profile is not None and not dry_run and result is not None:
        _apply_profile_post(result.output, render_profile, config, game_dir, ffmpeg_path)
    elif iterate and not dry_run and result is not None:
        from reeln.core.profiles import profiles_for_event

        profile_list = profiles_for_event(config, None)
        if profile_list:
            _apply_iterations_post(result.output, profile_list, config, game_dir, ffmpeg_path)


@app.command()
def highlights(
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Game directory (default: current directory)."
    ),
    render_profile: str | None = typer.Option(
        None, "--render-profile", "-r", help="Apply a named render profile after merge."
    ),
    iterate: bool = typer.Option(False, "--iterate", help="Multi-iteration mode using event type config."),
    profile: str | None = typer.Option(None, "--profile", help="Named config profile."),
    config_path: Path | None = typer.Option(None, "--config", help="Explicit config file path."),
    debug: bool = typer.Option(False, "--debug", help="Write debug artifacts to game debug directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without merging."),
) -> None:
    """Merge all segments into a full-game highlight reel."""
    try:
        config = load_config(path=config_path, profile=profile)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    activate_plugins(config.plugins)

    game_dir = _resolve_game_dir(output_dir, config.paths.output_dir)

    try:
        ffmpeg_path = discover_ffmpeg()
        result, messages = merge_game_highlights(
            game_dir,
            ffmpeg_path=ffmpeg_path,
            video_config=config.video,
            dry_run=dry_run,
        )
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for msg in messages:
        typer.echo(msg)

    if debug and not dry_run and result.ffmpeg_command:
        from reeln.core.debug import build_debug_artifact, write_debug_artifact, write_debug_index

        artifact = build_debug_artifact(
            "highlights_merge",
            result.ffmpeg_command,
            list(result.segment_files),
            result.output,
            game_dir,
            ffmpeg_path,
            extra={"copy": result.copy},
        )
        write_debug_artifact(game_dir, artifact)
        write_debug_index(game_dir)
        typer.echo(f"Debug: {game_dir / 'debug'}")

    # --render-profile takes precedence over --iterate
    if render_profile is not None and not dry_run and result is not None:
        _apply_profile_post(result.output, render_profile, config, game_dir, ffmpeg_path)
    elif iterate and not dry_run and result is not None:
        from reeln.core.profiles import profiles_for_event

        profile_list = profiles_for_event(config, None)
        if profile_list:
            _apply_iterations_post(result.output, profile_list, config, game_dir, ffmpeg_path)


@app.command()
def compile(
    event_type: str | None = typer.Option(None, "--type", "-t", help="Filter by event type."),
    segment_number: int | None = typer.Option(None, "--segment", "-s", help="Filter by segment number."),
    player: str | None = typer.Option(None, "--player", "-p", help="Filter by player."),
    output: Path | None = typer.Option(None, "--output", help="Output file path."),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Game directory."),
    profile: str | None = typer.Option(None, "--profile", help="Named config profile."),
    config_path: Path | None = typer.Option(None, "--config", help="Explicit config file path."),
    debug: bool = typer.Option(False, "--debug", help="Write debug artifacts to game debug directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without compiling."),
) -> None:
    """Compile raw event clips into a single video."""
    from reeln.core.events import compile_events

    try:
        config = load_config(path=config_path, profile=profile)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    activate_plugins(config.plugins)

    game_dir = _resolve_game_dir(output_dir, config.paths.output_dir)

    try:
        ffmpeg_path = discover_ffmpeg()
        result, messages = compile_events(
            game_dir,
            ffmpeg_path=ffmpeg_path,
            video_config=config.video,
            event_type=event_type,
            segment_number=segment_number,
            player=player,
            output=output,
            dry_run=dry_run,
        )
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for msg in messages:
        typer.echo(msg)

    if debug and not dry_run and result.ffmpeg_command:
        from reeln.core.debug import build_debug_artifact, write_debug_artifact, write_debug_index

        artifact = build_debug_artifact(
            "compile",
            result.ffmpeg_command,
            result.input_files,
            result.output,
            game_dir,
            ffmpeg_path,
            extra={"event_ids": result.event_ids, "copy": result.copy},
        )
        write_debug_artifact(game_dir, artifact)
        write_debug_index(game_dir)
        typer.echo(f"Debug: {game_dir / 'debug'}")


@app.command()
def finish(
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Game directory."),
    profile: str | None = typer.Option(None, "--profile", help="Named config profile."),
    config_path: Path | None = typer.Option(None, "--config", help="Explicit config file path."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without updating state."),
) -> None:
    """Finalize a game — mark as finished and show summary."""
    from reeln.core.finish import finish_game

    try:
        config = load_config(path=config_path, profile=profile)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    activate_plugins(config.plugins)

    game_dir = _resolve_game_dir(output_dir, config.paths.output_dir)

    try:
        _, messages = finish_game(game_dir, dry_run=dry_run)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for msg in messages:
        typer.echo(msg)


@app.command()
def prune(
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Game directory."),
    all_files: bool = typer.Option(False, "--all", help="Also remove raw event clips."),
    profile: str | None = typer.Option(None, "--profile", help="Named config profile."),
    config_path: Path | None = typer.Option(None, "--config", help="Explicit config file path."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be removed."),
) -> None:
    """Remove generated artifacts from a finished game."""
    from reeln.core.prune import prune_game

    try:
        config = load_config(path=config_path, profile=profile)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    game_dir = _resolve_game_dir(output_dir, config.paths.output_dir)

    try:
        _, messages = prune_game(game_dir, all_files=all_files, dry_run=dry_run)
    except ReelnError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    for msg in messages:
        typer.echo(msg)
