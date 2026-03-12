"""Game directory creation, state persistence, segment processing, and highlights merge."""

from __future__ import annotations

import fnmatch
import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reeln.core.errors import MediaError
from reeln.core.log import get_logger
from reeln.core.segment import get_sport, make_segments, segment_dir_name
from reeln.models.config import VideoConfig
from reeln.models.game import (
    GameEvent,
    GameInfo,
    GameState,
    dict_to_game_state,
    game_state_to_dict,
)
from reeln.models.render_plan import HighlightsResult, SegmentResult

log: logging.Logger = get_logger(__name__)

_GAME_STATE_FILE: str = "game.json"


# ---------------------------------------------------------------------------
# Directory naming
# ---------------------------------------------------------------------------


def game_dir_name(game_date: str, home: str, away: str, game_number: int = 1) -> str:
    """Build a game directory name.

    Examples::

        >>> game_dir_name("2026-02-26", "roseville", "mahtomedi")
        '2026-02-26_roseville_vs_mahtomedi'
        >>> game_dir_name("2026-02-26", "roseville", "mahtomedi", 2)
        '2026-02-26_roseville_vs_mahtomedi_g2'
    """
    name = f"{game_date}_{home}_vs_{away}"
    if game_number > 1:
        name += f"_g{game_number}"
    return name


# ---------------------------------------------------------------------------
# Double-header detection
# ---------------------------------------------------------------------------


def detect_next_game_number(base_dir: Path, game_date: str, home: str, away: str) -> int:
    """Scan *base_dir* for existing game directories and return the next number.

    Returns ``1`` if no matching directories exist.
    """
    if not base_dir.is_dir():
        return 1

    prefix = f"{game_date}_{home}_vs_{away}"
    game_number = 1
    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == prefix:
            # First game exists — next is at least 2
            game_number = max(game_number, 2)
        elif entry.name.startswith(prefix + "_g"):
            suffix = entry.name[len(prefix) + 2 :]
            if suffix.isdigit():
                game_number = max(game_number, int(suffix) + 1)
    return game_number


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


def create_game_directory(base_dir: Path, game_info: GameInfo) -> Path:
    """Create game directory with sport-specific segment subdirectories.

    Writes a ``game.json`` state file inside the new directory.
    Returns the path to the created game directory.
    """
    dir_name = game_dir_name(game_info.date, game_info.home_team, game_info.away_team, game_info.game_number)
    game_dir = base_dir / dir_name
    game_dir.mkdir(parents=True, exist_ok=True)

    # Create segment subdirectories
    segments = make_segments(game_info.sport)
    for seg in segments:
        seg_dir = game_dir / segment_dir_name(game_info.sport, seg.number)
        seg_dir.mkdir(exist_ok=True)

    # Write initial game state
    state = GameState(
        game_info=game_info,
        created_at=datetime.now(tz=UTC).isoformat(),
    )
    save_game_state(state, game_dir)

    return game_dir


# ---------------------------------------------------------------------------
# Init orchestrator
# ---------------------------------------------------------------------------


def init_game(
    base_dir: Path,
    game_info: GameInfo,
    *,
    dry_run: bool = False,
    home_profile: object | None = None,
    away_profile: object | None = None,
) -> tuple[Path, list[str]]:
    """Initialize a new game workspace.

    Auto-detects double-headers and adjusts ``game_info.game_number``.
    Returns ``(game_dir_path, log_messages)``.

    When *home_profile* / *away_profile* are provided they are included in the
    ``ON_GAME_INIT`` hook context so plugins can access team metadata.

    In dry-run mode, no files or directories are created.
    """
    # Validate sport early
    alias = get_sport(game_info.sport)

    # Auto-detect game number
    detected = detect_next_game_number(base_dir, game_info.date, game_info.home_team, game_info.away_team)
    game_info.game_number = detected

    dir_name = game_dir_name(game_info.date, game_info.home_team, game_info.away_team, game_info.game_number)
    game_dir = base_dir / dir_name

    segments = make_segments(game_info.sport)
    seg_names = [segment_dir_name(game_info.sport, s.number) for s in segments]

    messages: list[str] = []
    messages.append(f"Game directory: {game_dir}")
    messages.append(f"Sport: {alias.sport} ({alias.segment_count} {alias.segment_name}s)")
    for name in seg_names:
        messages.append(f"  {name}/")

    if dry_run:
        messages.insert(0, "Dry run — no files created")
        log.info("Dry run: would create %s", game_dir)
        return game_dir, messages

    game_dir = create_game_directory(base_dir, game_info)

    from reeln.plugins.hooks import Hook, HookContext
    from reeln.plugins.registry import get_registry

    hook_data: dict[str, Any] = {"game_dir": game_dir, "game_info": game_info}
    if home_profile is not None:
        hook_data["home_profile"] = home_profile
    if away_profile is not None:
        hook_data["away_profile"] = away_profile

    ctx = HookContext(hook=Hook.ON_GAME_INIT, data=hook_data)
    get_registry().emit(Hook.ON_GAME_INIT, ctx)

    # Second pass: plugins can now read shared data written by other plugins
    # (e.g. Google reads game_image/livestream_metadata written by OpenAI)
    ready_ctx = HookContext(hook=Hook.ON_GAME_READY, data=hook_data, shared=ctx.shared)
    get_registry().emit(Hook.ON_GAME_READY, ready_ctx)

    # Persist livestream URLs written by plugins (e.g. Google, Meta)
    livestreams = ready_ctx.shared.get("livestreams", {})
    if livestreams:
        state = load_game_state(game_dir)
        state.livestreams = dict(livestreams)
        save_game_state(state, game_dir)

    messages.append(f"Created {_GAME_STATE_FILE}")
    log.info("Game initialized: %s", game_dir)
    return game_dir, messages


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def load_game_state(game_dir: Path) -> GameState:
    """Read ``game.json`` from *game_dir*.

    Raises ``MediaError`` if the file is missing or contains invalid JSON.
    """
    state_file = game_dir / _GAME_STATE_FILE
    if not state_file.is_file():
        raise MediaError(f"Game state file not found: {state_file}")

    try:
        raw: Any = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise MediaError(f"Failed to read game state at {state_file}: {exc}") from exc

    if not isinstance(raw, dict):
        raise MediaError(f"Game state must be a JSON object, got {type(raw).__name__}")

    try:
        return dict_to_game_state(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaError(f"Invalid game state in {state_file}: {exc}") from exc


def save_game_state(state: GameState, game_dir: Path) -> Path:
    """Atomically write ``game.json`` to *game_dir*.

    Uses tempfile + ``Path.replace()`` to prevent corruption.
    """
    state_file = game_dir / _GAME_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    data = game_state_to_dict(state)
    content = json.dumps(data, indent=2) + "\n"

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=state_file.parent, text=True)
    try:
        with open(tmp_fd, "w") as tmp:
            tmp.write(content)
            tmp.flush()
        Path(tmp_name).replace(state_file)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

    log.debug("Game state saved to %s", state_file)
    return state_file


# ---------------------------------------------------------------------------
# Video file discovery
# ---------------------------------------------------------------------------


def find_segment_videos(segment_dir: Path, segment_alias: str) -> list[Path]:
    """Find video files in a segment directory, sorted by name.

    Excludes merged outputs (files starting with the segment alias prefix,
    e.g. ``period-1_``).
    """
    from reeln.core.ffmpeg import _VIDEO_EXTENSIONS

    if not segment_dir.is_dir():
        return []

    prefix = f"{segment_alias}_"
    videos: list[Path] = []
    for f in segment_dir.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in _VIDEO_EXTENSIONS:
            continue
        if f.name.startswith(prefix):
            continue
        videos.append(f)

    return sorted(videos, key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Replay collection
# ---------------------------------------------------------------------------


def collect_replays(
    source_dir: Path,
    source_glob: str,
    dest_dir: Path,
) -> list[Path]:
    """Move matching replay files from *source_dir* into *dest_dir*.

    Scans only top-level files in *source_dir* (not subdirectories).
    Files are **moved**, not copied — the source is cleared after collection.

    Returns the list of moved file paths (in *dest_dir*), sorted by name.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    candidates = sorted(
        (f for f in source_dir.iterdir() if f.is_file() and fnmatch.fnmatch(f.name, source_glob)),
        key=lambda p: p.name,
    )

    moved: list[Path] = []
    for src in candidates:
        dst = dest_dir / src.name
        shutil.move(str(src), str(dst))
        moved.append(dst)

    return moved


# ---------------------------------------------------------------------------
# Event creation
# ---------------------------------------------------------------------------


def create_events_for_segment(
    video_files: list[Path],
    segment_number: int,
    game_dir: Path,
) -> list[GameEvent]:
    """Create untagged ``GameEvent`` entries for each video file in a segment."""
    import uuid

    from reeln.plugins.hooks import Hook, HookContext
    from reeln.plugins.registry import get_registry

    registry = get_registry()

    now = datetime.now(tz=UTC).isoformat()
    events: list[GameEvent] = []
    for video in video_files:
        rel_path = str(video.relative_to(game_dir)) if video.is_relative_to(game_dir) else str(video)
        event = GameEvent(
            id=uuid.uuid4().hex,
            clip=rel_path,
            segment_number=segment_number,
            created_at=now,
        )
        events.append(event)
        registry.emit(
            Hook.ON_EVENT_CREATED,
            HookContext(hook=Hook.ON_EVENT_CREATED, data={"event": event}),
        )
    return events


# ---------------------------------------------------------------------------
# Segment processing
# ---------------------------------------------------------------------------


def process_segment(
    game_dir: Path,
    segment_number: int,
    *,
    ffmpeg_path: Path,
    video_config: VideoConfig | None = None,
    source_dir: Path | None = None,
    source_glob: str = "Replay_*.mkv",
    dry_run: bool = False,
) -> tuple[SegmentResult, list[str]]:
    """Collect replays and merge into a single highlight video.

    1. Load game state, validate segment number
    2. If *source_dir* is set, move matching replays into the segment dir
    3. Find video files in segment dir
    4. Detect mixed containers → copy vs re-encode
    5. Write concat file, build command, run ffmpeg
    6. Update game state (segments_processed)
    7. Return result + messages

    When *video_config* is provided, its encoding settings (codec, crf,
    audio_codec, etc.) are used for re-encode operations.  These settings
    come from the central config system and can be overridden via
    ``REELN_VIDEO_*`` environment variables.
    """
    from reeln.core.ffmpeg import (
        build_concat_command,
        run_ffmpeg,
        write_concat_file,
    )

    vc = video_config or VideoConfig()

    state = load_game_state(game_dir)
    sport = state.game_info.sport
    alias = segment_dir_name(sport, segment_number)
    seg_dir = game_dir / alias

    if not seg_dir.is_dir():
        raise MediaError(f"Segment directory not found: {seg_dir}")

    # Collect replays from source directory
    collected: list[Path] = []
    if source_dir is not None:
        collected = collect_replays(source_dir, source_glob, seg_dir)
        if not collected:
            raise MediaError(f"No files matching '{source_glob}' in {source_dir}")

    videos = find_segment_videos(seg_dir, alias)
    if not videos:
        raise MediaError(f"No video files found in {seg_dir}")

    # Detect mixed containers
    extensions = {f.suffix.lower() for f in videos}
    copy = len(extensions) <= 1

    output_name = f"{alias}_{state.game_info.date}.mkv"
    output = game_dir.parent / output_name

    messages: list[str] = []
    if collected:
        messages.append(f"Collected {len(collected)} replay(s) from {source_dir}")
    messages.append(f"Segment: {alias}")
    messages.append(f"Input files: {len(videos)}")
    for v in videos:
        messages.append(f"  {v.name}")
    messages.append(f"Mode: {'stream copy' if copy else 're-encode (mixed containers)'}")
    messages.append(f"Output: {output}")

    # Count events that would be created (for dry-run reporting)
    existing_clips = {e.clip for e in state.events}
    candidate_events = create_events_for_segment(videos, segment_number, game_dir)
    new_events = [e for e in candidate_events if e.clip not in existing_clips]
    events_created = len(new_events)

    if events_created:
        messages.append(f"Events: {events_created} new")

    if dry_run:
        result = SegmentResult(
            segment_number=segment_number,
            segment_dir=seg_dir,
            input_files=list(videos),
            output=output,
            copy=copy,
            events_created=events_created,
        )
        messages.insert(0, "Dry run — no files written")
        log.info("Dry run: would merge %d files into %s", len(videos), output)
        return result, messages

    from reeln.plugins.hooks import Hook, HookContext
    from reeln.plugins.registry import get_registry

    get_registry().emit(
        Hook.ON_SEGMENT_START,
        HookContext(
            hook=Hook.ON_SEGMENT_START,
            data={
                "game_dir": game_dir,
                "segment_number": segment_number,
                "segment_dir": seg_dir,
                "segment_alias": alias,
            },
        ),
    )

    concat_file = write_concat_file(videos, seg_dir)
    cmd: list[str] = []
    try:
        cmd = build_concat_command(
            ffmpeg_path,
            concat_file,
            output,
            copy=copy,
            video_codec=vc.codec,
            crf=vc.crf,
            audio_codec=vc.audio_codec,
        )
        try:
            run_ffmpeg(cmd)
        except Exception as exc:
            from reeln.core.errors import emit_on_error

            emit_on_error(exc, context={"operation": "process_segment", "segment": alias})
            raise
    finally:
        concat_file.unlink(missing_ok=True)

    result = SegmentResult(
        segment_number=segment_number,
        segment_dir=seg_dir,
        input_files=list(videos),
        output=output,
        copy=copy,
        events_created=events_created,
        ffmpeg_command=list(cmd),
    )

    # Update game state
    state.events.extend(new_events)
    if segment_number not in state.segments_processed:
        state.segments_processed.append(segment_number)
    save_game_state(state, game_dir)

    get_registry().emit(
        Hook.ON_CLIP_AVAILABLE,
        HookContext(hook=Hook.ON_CLIP_AVAILABLE, data={"output": output, "segment": alias}),
    )

    get_registry().emit(
        Hook.ON_SEGMENT_COMPLETE,
        HookContext(
            hook=Hook.ON_SEGMENT_COMPLETE,
            data={
                "game_dir": game_dir,
                "segment_number": segment_number,
                "output": output,
                "events_created": events_created,
            },
        ),
    )

    messages.append("Merge complete")
    log.info("Segment %s merged: %s", alias, output)
    return result, messages


# ---------------------------------------------------------------------------
# Game highlights merge
# ---------------------------------------------------------------------------


def merge_game_highlights(
    game_dir: Path,
    *,
    ffmpeg_path: Path,
    video_config: VideoConfig | None = None,
    dry_run: bool = False,
) -> tuple[HighlightsResult, list[str]]:
    """Merge all segment highlights into a story-of-the-game highlight reel.

    1. Load game state
    2. Find segment highlight files (pattern: {alias}-N_{date}.mkv)
    3. Merge via concat
    4. Update game state (highlighted = True)
    5. Return result + messages

    When *video_config* is provided, its encoding settings are used for
    re-encode operations.
    """
    from reeln.core.ffmpeg import (
        build_concat_command,
        run_ffmpeg,
        write_concat_file,
    )

    vc = video_config or VideoConfig()

    state = load_game_state(game_dir)
    info = state.game_info
    sport = info.sport
    alias_info = get_sport(sport)

    # Find segment highlight files in order
    segment_files: list[Path] = []
    segments = make_segments(sport)
    for seg in segments:
        seg_alias = segment_dir_name(sport, seg.number)
        pattern = f"{seg_alias}_{info.date}.mkv"
        candidate = game_dir.parent / pattern
        if candidate.is_file():
            segment_files.append(candidate)

    if not segment_files:
        raise MediaError(f"No segment highlight files found in {game_dir.parent}. Run 'reeln game segment' first.")

    # Detect mixed containers
    extensions = {f.suffix.lower() for f in segment_files}
    copy = len(extensions) <= 1

    output_name = f"{info.home_team}_vs_{info.away_team}_{info.date}.mkv"
    output = game_dir.parent / output_name

    messages: list[str] = []
    messages.append(f"Sport: {alias_info.sport}")
    messages.append(f"Segment files: {len(segment_files)}")
    for sf in segment_files:
        messages.append(f"  {sf.name}")
    messages.append(f"Mode: {'stream copy' if copy else 're-encode (mixed containers)'}")
    messages.append(f"Output: {output}")

    if dry_run:
        result = HighlightsResult(
            output=output,
            segment_files=list(segment_files),
            copy=copy,
        )
        messages.insert(0, "Dry run — no files written")
        log.info("Dry run: would merge %d segments into %s", len(segment_files), output)
        return result, messages

    concat_file = write_concat_file(segment_files, game_dir)
    cmd: list[str] = []
    try:
        cmd = build_concat_command(
            ffmpeg_path,
            concat_file,
            output,
            copy=copy,
            video_codec=vc.codec,
            crf=vc.crf,
            audio_codec=vc.audio_codec,
        )
        try:
            run_ffmpeg(cmd)
        except Exception as exc:
            from reeln.core.errors import emit_on_error

            emit_on_error(exc, context={"operation": "merge_game_highlights"})
            raise
    finally:
        concat_file.unlink(missing_ok=True)

    result = HighlightsResult(
        output=output,
        segment_files=list(segment_files),
        copy=copy,
        ffmpeg_command=list(cmd),
    )

    # Update game state
    state.highlighted = True
    save_game_state(state, game_dir)

    from reeln.plugins.hooks import Hook, HookContext
    from reeln.plugins.registry import get_registry

    get_registry().emit(
        Hook.ON_HIGHLIGHTS_MERGED,
        HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED,
            data={"output": output, "segment_files": segment_files},
        ),
    )

    messages.append("Highlights merge complete")
    log.info("Game highlights merged: %s", output)
    return result, messages
