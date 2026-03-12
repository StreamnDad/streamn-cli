"""Tests for game directory creation, state persistence, segment processing, and highlights merge."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from reeln.core.errors import MediaError
from reeln.core.highlights import (
    collect_replays,
    create_events_for_segment,
    create_game_directory,
    detect_next_game_number,
    find_segment_videos,
    game_dir_name,
    init_game,
    load_game_state,
    merge_game_highlights,
    process_segment,
    save_game_state,
)
from reeln.models.game import GameInfo, GameState
from reeln.plugins.hooks import Hook, HookContext
from reeln.plugins.registry import get_registry

# ---------------------------------------------------------------------------
# game_dir_name
# ---------------------------------------------------------------------------


def test_game_dir_name_basic() -> None:
    assert game_dir_name("2026-02-26", "roseville", "mahtomedi") == ("2026-02-26_roseville_vs_mahtomedi")


def test_game_dir_name_game_number_1_no_suffix() -> None:
    assert game_dir_name("2026-02-26", "a", "b", game_number=1) == "2026-02-26_a_vs_b"


def test_game_dir_name_double_header() -> None:
    assert game_dir_name("2026-02-26", "a", "b", game_number=2) == "2026-02-26_a_vs_b_g2"


def test_game_dir_name_triple_header() -> None:
    assert game_dir_name("2026-02-26", "a", "b", game_number=3) == "2026-02-26_a_vs_b_g3"


# ---------------------------------------------------------------------------
# detect_next_game_number
# ---------------------------------------------------------------------------


def test_detect_next_game_number_no_existing(tmp_path: Path) -> None:
    assert detect_next_game_number(tmp_path, "2026-02-26", "a", "b") == 1


def test_detect_next_game_number_base_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    assert detect_next_game_number(missing, "2026-02-26", "a", "b") == 1


def test_detect_next_game_number_one_exists(tmp_path: Path) -> None:
    (tmp_path / "2026-02-26_a_vs_b").mkdir()
    assert detect_next_game_number(tmp_path, "2026-02-26", "a", "b") == 2


def test_detect_next_game_number_two_exist(tmp_path: Path) -> None:
    (tmp_path / "2026-02-26_a_vs_b").mkdir()
    (tmp_path / "2026-02-26_a_vs_b_g2").mkdir()
    assert detect_next_game_number(tmp_path, "2026-02-26", "a", "b") == 3


def test_detect_next_game_number_ignores_unrelated(tmp_path: Path) -> None:
    (tmp_path / "2026-02-26_x_vs_y").mkdir()
    (tmp_path / "some_file.txt").touch()
    assert detect_next_game_number(tmp_path, "2026-02-26", "a", "b") == 1


def test_detect_next_game_number_ignores_non_numeric_suffix(tmp_path: Path) -> None:
    (tmp_path / "2026-02-26_a_vs_b_gX").mkdir()
    assert detect_next_game_number(tmp_path, "2026-02-26", "a", "b") == 1


# ---------------------------------------------------------------------------
# create_game_directory
# ---------------------------------------------------------------------------


def test_create_game_directory_hockey(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="roseville", away_team="mahtomedi", sport="hockey")
    game_dir = create_game_directory(tmp_path, info)

    assert game_dir.is_dir()
    assert game_dir.name == "2026-02-26_roseville_vs_mahtomedi"
    assert (game_dir / "period-1").is_dir()
    assert (game_dir / "period-2").is_dir()
    assert (game_dir / "period-3").is_dir()
    assert (game_dir / "game.json").is_file()


def test_create_game_directory_basketball(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="lakers", away_team="celtics", sport="basketball")
    game_dir = create_game_directory(tmp_path, info)

    assert (game_dir / "quarter-1").is_dir()
    assert (game_dir / "quarter-2").is_dir()
    assert (game_dir / "quarter-3").is_dir()
    assert (game_dir / "quarter-4").is_dir()


def test_create_game_directory_generic(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="generic")
    game_dir = create_game_directory(tmp_path, info)

    assert (game_dir / "segment-1").is_dir()
    # generic has only 1 segment
    assert not (game_dir / "segment-2").exists()


def test_create_game_directory_writes_valid_state(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir = create_game_directory(tmp_path, info)

    state = load_game_state(game_dir)
    assert state.game_info.date == "2026-02-26"
    assert state.game_info.home_team == "a"
    assert state.game_info.sport == "hockey"
    assert state.segments_processed == []
    assert state.highlighted is False
    assert state.finished is False
    assert state.created_at != ""


def test_create_game_directory_double_header(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey", game_number=2)
    game_dir = create_game_directory(tmp_path, info)
    assert game_dir.name == "2026-02-26_a_vs_b_g2"


# ---------------------------------------------------------------------------
# init_game
# ---------------------------------------------------------------------------


def test_init_game_creates_directory(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir, messages = init_game(tmp_path, info)

    assert game_dir.is_dir()
    assert (game_dir / "game.json").is_file()
    assert any("Game directory:" in m for m in messages)
    assert any("game.json" in m for m in messages)


def test_init_game_dry_run(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir, messages = init_game(tmp_path, info, dry_run=True)

    # Dry run: no files or directories created
    assert not game_dir.exists()
    assert any("Dry run" in m for m in messages)


def test_init_game_auto_game_number(tmp_path: Path) -> None:
    # Create first game
    info1 = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir1, _ = init_game(tmp_path, info1)
    assert game_dir1.name == "2026-02-26_a_vs_b"

    # Second init auto-detects double-header
    info2 = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir2, _ = init_game(tmp_path, info2)
    assert game_dir2.name == "2026-02-26_a_vs_b_g2"


def test_init_game_invalid_sport(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="quidditch")
    with pytest.raises(Exception, match="Unknown sport"):
        init_game(tmp_path, info)


def test_init_game_messages_include_sport_info(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="basketball")
    _, messages = init_game(tmp_path, info)

    assert any("basketball" in m for m in messages)
    assert any("quarter" in m for m in messages)


# ---------------------------------------------------------------------------
# load_game_state
# ---------------------------------------------------------------------------


def test_load_game_state_valid(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    create_game_directory(tmp_path, info)
    game_dir = tmp_path / "2026-02-26_a_vs_b"

    state = load_game_state(game_dir)
    assert state.game_info.date == "2026-02-26"
    assert state.game_info.sport == "hockey"


def test_load_game_state_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MediaError, match="not found"):
        load_game_state(tmp_path)


def test_load_game_state_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("not valid json{{{", encoding="utf-8")
    with pytest.raises(MediaError, match="Failed to read"):
        load_game_state(tmp_path)


def test_load_game_state_not_dict(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(MediaError, match="must be a JSON object"):
        load_game_state(tmp_path)


def test_load_game_state_invalid_structure(tmp_path: Path) -> None:
    (tmp_path / "game.json").write_text('{"bad": "data"}', encoding="utf-8")
    with pytest.raises(MediaError, match="Invalid game state"):
        load_game_state(tmp_path)


# ---------------------------------------------------------------------------
# save_game_state
# ---------------------------------------------------------------------------


def test_save_game_state_writes_valid_json(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    state = GameState(game_info=info, created_at="2026-02-26T12:00:00+00:00")

    result_path = save_game_state(state, tmp_path)
    assert result_path == tmp_path / "game.json"
    assert result_path.is_file()

    raw = json.loads(result_path.read_text(encoding="utf-8"))
    assert raw["game_info"]["home_team"] == "a"
    assert raw["created_at"] == "2026-02-26T12:00:00+00:00"


def test_save_game_state_overwrites_existing(tmp_path: Path) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")

    state1 = GameState(game_info=info, created_at="t1")
    save_game_state(state1, tmp_path)

    state2 = GameState(game_info=info, segments_processed=[1, 2], created_at="t2")
    save_game_state(state2, tmp_path)

    loaded = load_game_state(tmp_path)
    assert loaded.segments_processed == [1, 2]
    assert loaded.created_at == "t2"


def test_save_game_state_cleans_up_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    state = GameState(game_info=info, created_at="t1")

    # Make Path.replace raise to trigger cleanup branch
    def failing_replace(self: Path, target: str | Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        save_game_state(state, tmp_path)

    # Temp file should be cleaned up
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_save_game_state_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="generic")
    state = GameState(game_info=info, created_at="t1")
    result = save_game_state(state, nested)
    assert result.is_file()


# ---------------------------------------------------------------------------
# Helpers for segment/highlights tests
# ---------------------------------------------------------------------------


def _make_game_dir(tmp_path: Path, sport: str = "hockey") -> Path:
    """Create a game directory and return its path."""
    info = GameInfo(date="2026-02-26", home_team="roseville", away_team="mahtomedi", sport=sport)
    return create_game_directory(tmp_path, info)


def _mock_ffmpeg_success() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


# ---------------------------------------------------------------------------
# find_segment_videos
# ---------------------------------------------------------------------------


def test_find_segment_videos_finds_videos(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "replay2.mkv").touch()

    result = find_segment_videos(seg_dir, "period-1")
    assert len(result) == 2
    assert result[0].name == "replay1.mkv"
    assert result[1].name == "replay2.mkv"


def test_find_segment_videos_excludes_non_video(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "notes.txt").touch()
    (seg_dir / "thumbnail.jpg").touch()

    result = find_segment_videos(seg_dir, "period-1")
    assert len(result) == 1
    assert result[0].name == "replay1.mkv"


def test_find_segment_videos_excludes_merged_outputs(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "period-1_2026-02-26.mkv").touch()  # merged output

    result = find_segment_videos(seg_dir, "period-1")
    assert len(result) == 1
    assert result[0].name == "replay1.mkv"


def test_find_segment_videos_sorted_by_name(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    (seg_dir / "c_replay.mkv").touch()
    (seg_dir / "a_replay.mkv").touch()
    (seg_dir / "b_replay.mkv").touch()

    result = find_segment_videos(seg_dir, "period-1")
    names = [f.name for f in result]
    assert names == ["a_replay.mkv", "b_replay.mkv", "c_replay.mkv"]


def test_find_segment_videos_empty_dir(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    assert find_segment_videos(seg_dir, "period-1") == []


def test_find_segment_videos_missing_dir(tmp_path: Path) -> None:
    assert find_segment_videos(tmp_path / "nonexistent", "period-1") == []


def test_find_segment_videos_excludes_subdirectories(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "subdir").mkdir()

    result = find_segment_videos(seg_dir, "period-1")
    assert len(result) == 1


def test_find_segment_videos_multiple_extensions(tmp_path: Path) -> None:
    seg_dir = tmp_path / "period-1"
    seg_dir.mkdir()
    (seg_dir / "a.mkv").touch()
    (seg_dir / "b.mp4").touch()
    (seg_dir / "c.mov").touch()

    result = find_segment_videos(seg_dir, "period-1")
    assert len(result) == 3


# ---------------------------------------------------------------------------
# collect_replays
# ---------------------------------------------------------------------------


def test_collect_replays_moves_matching_files(tmp_path: Path) -> None:
    src = tmp_path / "source"
    src.mkdir()
    (src / "Replay_001.mkv").write_bytes(b"a")
    (src / "Replay_002.mkv").write_bytes(b"b")
    (src / "Manual_clip.mkv").write_bytes(b"c")

    dest = tmp_path / "period-1"
    moved = collect_replays(src, "Replay_*.mkv", dest)

    assert len(moved) == 2
    assert all(f.parent == dest for f in moved)
    assert (dest / "Replay_001.mkv").is_file()
    assert (dest / "Replay_002.mkv").is_file()
    # Source files are gone
    assert not (src / "Replay_001.mkv").exists()
    assert not (src / "Replay_002.mkv").exists()
    # Non-matching file remains
    assert (src / "Manual_clip.mkv").is_file()


def test_collect_replays_sorted_by_name(tmp_path: Path) -> None:
    src = tmp_path / "source"
    src.mkdir()
    (src / "Replay_b.mkv").write_bytes(b"b")
    (src / "Replay_a.mkv").write_bytes(b"a")

    moved = collect_replays(src, "Replay_*.mkv", tmp_path / "dest")
    assert [f.name for f in moved] == ["Replay_a.mkv", "Replay_b.mkv"]


def test_collect_replays_creates_dest_dir(tmp_path: Path) -> None:
    src = tmp_path / "source"
    src.mkdir()
    (src / "Replay_001.mkv").write_bytes(b"a")

    dest = tmp_path / "deep" / "nested" / "period-1"
    moved = collect_replays(src, "Replay_*.mkv", dest)

    assert len(moved) == 1
    assert dest.is_dir()


def test_collect_replays_skips_directories(tmp_path: Path) -> None:
    src = tmp_path / "source"
    src.mkdir()
    (src / "Replay_dir.mkv").mkdir()
    (src / "Replay_file.mkv").write_bytes(b"a")

    moved = collect_replays(src, "Replay_*.mkv", tmp_path / "dest")
    assert len(moved) == 1
    assert moved[0].name == "Replay_file.mkv"


def test_collect_replays_no_matches(tmp_path: Path) -> None:
    src = tmp_path / "source"
    src.mkdir()
    (src / "Manual_clip.mkv").write_bytes(b"a")

    moved = collect_replays(src, "Replay_*.mkv", tmp_path / "dest")
    assert moved == []


def test_collect_replays_custom_glob(tmp_path: Path) -> None:
    src = tmp_path / "source"
    src.mkdir()
    (src / "Game_001.mp4").write_bytes(b"a")
    (src / "Replay_001.mkv").write_bytes(b"b")

    moved = collect_replays(src, "Game_*.mp4", tmp_path / "dest")
    assert len(moved) == 1
    assert moved[0].name == "Game_001.mp4"


# ---------------------------------------------------------------------------
# create_events_for_segment
# ---------------------------------------------------------------------------


def test_create_events_for_segment_basic(tmp_path: Path) -> None:
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    seg_dir = game_dir / "period-1"
    seg_dir.mkdir()
    f1 = seg_dir / "replay1.mkv"
    f2 = seg_dir / "replay2.mkv"
    f1.touch()
    f2.touch()

    events = create_events_for_segment([f1, f2], 1, game_dir)
    assert len(events) == 2
    assert events[0].clip == "period-1/replay1.mkv"
    assert events[1].clip == "period-1/replay2.mkv"
    assert events[0].segment_number == 1
    assert events[0].event_type == ""
    assert events[0].player == ""
    assert events[0].id != events[1].id
    assert events[0].created_at != ""


def test_create_events_for_segment_absolute_path(tmp_path: Path) -> None:
    """Files outside game_dir use absolute paths."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    f1 = other / "replay.mkv"
    f1.touch()

    events = create_events_for_segment([f1], 1, game_dir)
    assert len(events) == 1
    assert events[0].clip == str(f1)


def test_create_events_for_segment_empty(tmp_path: Path) -> None:
    events = create_events_for_segment([], 1, tmp_path)
    assert events == []


# ---------------------------------------------------------------------------
# process_segment
# ---------------------------------------------------------------------------


def test_process_segment_merges_files(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "replay2.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, messages = process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert result.segment_number == 1
    assert result.output == tmp_path / "period-1_2026-02-26.mkv"
    assert len(result.input_files) == 2
    assert result.copy is True
    assert any("Merge complete" in m for m in messages)


def test_process_segment_golden_command(tmp_path: Path) -> None:
    """Golden assertion: verify the exact ffmpeg command built for segment merge."""
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    captured_cmd: list[str] = []

    def capture_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_cmd.extend(cmd)
        return _mock_ffmpeg_success()

    with patch("reeln.core.ffmpeg.subprocess.run", side_effect=capture_run):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert captured_cmd[0] == "/usr/bin/ffmpeg"
    assert "-y" in captured_cmd
    assert "-f" in captured_cmd
    assert "concat" in captured_cmd
    assert "-c" in captured_cmd
    assert "copy" in captured_cmd
    assert captured_cmd[-1] == str(tmp_path / "period-1_2026-02-26.mkv")


def test_process_segment_dry_run(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    result, messages = process_segment(game_dir, 1, ffmpeg_path=ffmpeg, dry_run=True)

    assert any("Dry run" in m for m in messages)
    assert result.output == tmp_path / "period-1_2026-02-26.mkv"
    # State NOT updated in dry run
    state = load_game_state(game_dir)
    assert 1 not in state.segments_processed


def test_process_segment_missing_dir(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    # Remove the segment directory
    (game_dir / "period-1").rmdir()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with pytest.raises(MediaError, match="Segment directory not found"):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)


def test_process_segment_no_videos(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    # period-1 exists but is empty

    ffmpeg = Path("/usr/bin/ffmpeg")
    with pytest.raises(MediaError, match="No video files found"):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)


def test_process_segment_mixed_containers_reencode(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "replay2.mp4").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, messages = process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert result.copy is False
    assert any("re-encode" in m for m in messages)


def test_process_segment_uses_video_config(tmp_path: Path) -> None:
    """VideoConfig encoding settings flow through to ffmpeg command."""
    from reeln.models.config import VideoConfig

    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "replay2.mp4").touch()  # mixed → re-encode

    vc = VideoConfig(codec="libx265", crf=22, audio_codec="opus")
    ffmpeg = Path("/usr/bin/ffmpeg")
    captured_cmd: list[str] = []

    def capture_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_cmd.extend(cmd)
        return _mock_ffmpeg_success()

    with patch("reeln.core.ffmpeg.subprocess.run", side_effect=capture_run):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg, video_config=vc)

    assert "-c:v" in captured_cmd
    idx = captured_cmd.index("-c:v")
    assert captured_cmd[idx + 1] == "libx265"
    assert "-crf" in captured_cmd
    idx = captured_cmd.index("-crf")
    assert captured_cmd[idx + 1] == "22"
    assert "-c:a" in captured_cmd
    idx = captured_cmd.index("-c:a")
    assert captured_cmd[idx + 1] == "opus"


def test_process_segment_updates_state(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    state = load_game_state(game_dir)
    assert 1 in state.segments_processed


def test_process_segment_idempotent_state(tmp_path: Path) -> None:
    """Running segment twice doesn't duplicate the segment number in state."""
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)
        # replay1.mkv is now excluded (starts with period-1_) but add another
        (seg_dir / "replay2.mkv").touch()
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    state = load_game_state(game_dir)
    assert state.segments_processed.count(1) == 1


def test_process_segment_cleans_up_concat_file(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    # No leftover .txt concat files
    txt_files = list(seg_dir.glob("*.txt"))
    assert txt_files == []


def test_process_segment_cleans_up_concat_on_error(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    fail_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="fail")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.core.ffmpeg.subprocess.run", return_value=fail_proc),
        pytest.raises(FFmpegError),
    ):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    # Concat file cleaned up even on failure
    txt_files = list(seg_dir.glob("*.txt"))
    assert txt_files == []


# ---------------------------------------------------------------------------
# process_segment with source_dir
# ---------------------------------------------------------------------------


def test_process_segment_collects_from_source(tmp_path: Path) -> None:
    """When source_dir is set, replays are moved into the segment dir first."""
    game_dir = _make_game_dir(tmp_path)
    src = tmp_path / "replays"
    src.mkdir()
    (src / "Replay_001.mkv").write_bytes(b"video")

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, messages = process_segment(
            game_dir,
            1,
            ffmpeg_path=ffmpeg,
            source_dir=src,
        )

    assert result.segment_number == 1
    assert any("Collected 1 replay" in m for m in messages)
    # File was moved
    assert not (src / "Replay_001.mkv").exists()
    assert (game_dir / "period-1" / "Replay_001.mkv").is_file()


def test_process_segment_collects_with_custom_glob(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    src = tmp_path / "replays"
    src.mkdir()
    (src / "Game_001.mp4").write_bytes(b"video")
    (src / "Replay_001.mkv").write_bytes(b"other")

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, _messages = process_segment(
            game_dir,
            1,
            ffmpeg_path=ffmpeg,
            source_dir=src,
            source_glob="Game_*.mp4",
        )

    assert len(result.input_files) == 1
    assert result.input_files[0].name == "Game_001.mp4"
    # Only matching file was moved
    assert (src / "Replay_001.mkv").is_file()


def test_process_segment_collect_no_matches(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    src = tmp_path / "replays"
    src.mkdir()
    (src / "Manual_clip.mkv").write_bytes(b"data")

    ffmpeg = Path("/usr/bin/ffmpeg")
    with pytest.raises(MediaError, match="No files matching"):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg, source_dir=src)


def test_process_segment_collect_dry_run(tmp_path: Path) -> None:
    """Dry run still collects replays but doesn't merge."""
    game_dir = _make_game_dir(tmp_path)
    src = tmp_path / "replays"
    src.mkdir()
    (src / "Replay_001.mkv").write_bytes(b"video")

    ffmpeg = Path("/usr/bin/ffmpeg")
    _result, messages = process_segment(
        game_dir,
        1,
        ffmpeg_path=ffmpeg,
        source_dir=src,
        dry_run=True,
    )

    assert any("Collected 1 replay" in m for m in messages)
    assert any("Dry run" in m for m in messages)
    # File was moved even in dry run (collect always happens)
    assert (game_dir / "period-1" / "Replay_001.mkv").is_file()


# ---------------------------------------------------------------------------
# process_segment — event creation
# ---------------------------------------------------------------------------


def test_process_segment_creates_events(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()
    (seg_dir / "replay2.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, messages = process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert result.events_created == 2
    assert any("Events: 2 new" in m for m in messages)

    state = load_game_state(game_dir)
    assert len(state.events) == 2
    clips = {e.clip for e in state.events}
    assert "period-1/replay1.mkv" in clips
    assert "period-1/replay2.mkv" in clips


def test_process_segment_events_idempotent(tmp_path: Path) -> None:
    """Running segment twice doesn't duplicate events."""
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result1, _ = process_segment(game_dir, 1, ffmpeg_path=ffmpeg)
        # Add a second file for re-run
        (seg_dir / "replay2.mkv").touch()
        result2, _ = process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert result1.events_created == 1
    assert result2.events_created == 1  # only the new file
    state = load_game_state(game_dir)
    assert len(state.events) == 2


def test_process_segment_events_dry_run(tmp_path: Path) -> None:
    """Dry run reports events but doesn't persist them."""
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    result, messages = process_segment(game_dir, 1, ffmpeg_path=ffmpeg, dry_run=True)

    assert result.events_created == 1
    assert any("Events: 1 new" in m for m in messages)
    # Events NOT persisted in dry run
    state = load_game_state(game_dir)
    assert len(state.events) == 0


def test_process_segment_events_no_new(tmp_path: Path) -> None:
    """When all files already have events, events_created is 0."""
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)
        result, messages = process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert result.events_created == 0
    assert not any("Events:" in m for m in messages)


# ---------------------------------------------------------------------------
# merge_game_highlights
# ---------------------------------------------------------------------------


def test_merge_game_highlights_merges(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    # Create segment highlight files in game directory
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, messages = merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    assert result.output == tmp_path / "roseville_vs_mahtomedi_2026-02-26.mkv"
    assert len(result.segment_files) == 3
    assert result.copy is True
    assert any("Highlights merge complete" in m for m in messages)


def test_merge_game_highlights_golden_command(tmp_path: Path) -> None:
    """Golden assertion: verify the exact ffmpeg command built for highlights merge."""
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    captured_cmd: list[str] = []

    def capture_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_cmd.extend(cmd)
        return _mock_ffmpeg_success()

    with patch("reeln.core.ffmpeg.subprocess.run", side_effect=capture_run):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    assert captured_cmd[0] == "/usr/bin/ffmpeg"
    assert "-y" in captured_cmd
    assert "-f" in captured_cmd
    assert "concat" in captured_cmd
    assert "-c" in captured_cmd
    assert "copy" in captured_cmd
    assert captured_cmd[-1] == str(tmp_path / "roseville_vs_mahtomedi_2026-02-26.mkv")


def test_merge_game_highlights_dry_run(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    _result, messages = merge_game_highlights(game_dir, ffmpeg_path=ffmpeg, dry_run=True)

    assert any("Dry run" in m for m in messages)
    # State NOT updated in dry run
    state = load_game_state(game_dir)
    assert state.highlighted is False


def test_merge_game_highlights_uses_video_config(tmp_path: Path) -> None:
    """VideoConfig encoding settings flow through to ffmpeg command."""
    from reeln.models.config import VideoConfig

    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    vc = VideoConfig(codec="libx265", crf=22, audio_codec="opus")
    ffmpeg = Path("/usr/bin/ffmpeg")

    # All segment files are .mkv → copy mode → config doesn't apply to command
    # So we verify it's accepted without error (copy mode skips encoding args)
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, _ = merge_game_highlights(game_dir, ffmpeg_path=ffmpeg, video_config=vc)

    assert result.copy is True


def test_merge_game_highlights_no_segment_files(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)

    ffmpeg = Path("/usr/bin/ffmpeg")
    with pytest.raises(MediaError, match="No segment highlight files found"):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)


def test_merge_game_highlights_updates_state(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    state = load_game_state(game_dir)
    assert state.highlighted is True


def test_merge_game_highlights_partial_segments(tmp_path: Path) -> None:
    """Only segments that have highlight files are included."""
    game_dir = _make_game_dir(tmp_path)
    # Only period 1 and 3 have highlights
    (tmp_path / "period-1_2026-02-26.mkv").touch()
    (tmp_path / "period-3_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        result, _ = merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    assert len(result.segment_files) == 2


def test_merge_game_highlights_cleans_up_concat_file(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    txt_files = list(game_dir.glob("*.txt"))
    assert txt_files == []


def test_merge_game_highlights_cleans_up_concat_on_error(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    ffmpeg = Path("/usr/bin/ffmpeg")
    fail_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="fail")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.core.ffmpeg.subprocess.run", return_value=fail_proc),
        pytest.raises(FFmpegError),
    ):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    txt_files = list(game_dir.glob("*.txt"))
    assert txt_files == []


# ---------------------------------------------------------------------------
# Hook emissions
# ---------------------------------------------------------------------------


def test_init_game_emits_on_game_init(tmp_path: Path) -> None:
    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_GAME_INIT, emitted.append)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    init_game(tmp_path, info)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_GAME_INIT
    assert "game_dir" in emitted[0].data
    assert "game_info" in emitted[0].data


def test_init_game_dry_run_no_hook(tmp_path: Path) -> None:
    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_GAME_INIT, emitted.append)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    init_game(tmp_path, info, dry_run=True)

    assert len(emitted) == 0


def test_init_game_persists_livestreams(tmp_path: Path) -> None:
    """Livestream URLs written to context.shared by plugins are saved to game.json."""

    def fake_plugin(ctx: HookContext) -> None:
        ctx.shared["livestreams"] = {"google": "https://youtube.com/live/abc123"}

    get_registry().register(Hook.ON_GAME_INIT, fake_plugin)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir, _ = init_game(tmp_path, info)

    state = load_game_state(game_dir)
    assert state.livestreams == {"google": "https://youtube.com/live/abc123"}


def test_init_game_emits_on_game_ready(tmp_path: Path) -> None:
    """ON_GAME_READY fires after ON_GAME_INIT with shared context."""
    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_GAME_READY, emitted.append)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    init_game(tmp_path, info)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_GAME_READY
    assert "game_dir" in emitted[0].data
    assert "game_info" in emitted[0].data


def test_init_game_on_game_ready_shares_context(tmp_path: Path) -> None:
    """Data written to shared during ON_GAME_INIT is visible in ON_GAME_READY."""
    ready_shared: list[dict[str, Any]] = []

    def init_handler(ctx: HookContext) -> None:
        ctx.shared["game_image"] = "/tmp/thumbnail.png"

    def ready_handler(ctx: HookContext) -> None:
        ready_shared.append(dict(ctx.shared))

    get_registry().register(Hook.ON_GAME_INIT, init_handler)
    get_registry().register(Hook.ON_GAME_READY, ready_handler)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    init_game(tmp_path, info)

    assert len(ready_shared) == 1
    assert ready_shared[0]["game_image"] == "/tmp/thumbnail.png"


def test_init_game_dry_run_no_game_ready_hook(tmp_path: Path) -> None:
    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_GAME_READY, emitted.append)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    init_game(tmp_path, info, dry_run=True)

    assert len(emitted) == 0


def test_init_game_on_game_ready_livestreams_persisted(tmp_path: Path) -> None:
    """Livestream URLs updated during ON_GAME_READY are persisted to game.json."""

    def ready_handler(ctx: HookContext) -> None:
        ctx.shared["livestreams"] = ctx.shared.get("livestreams", {})
        ctx.shared["livestreams"]["google"] = "https://youtube.com/live/updated"

    get_registry().register(Hook.ON_GAME_READY, ready_handler)

    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir, _ = init_game(tmp_path, info)

    state = load_game_state(game_dir)
    assert state.livestreams == {"google": "https://youtube.com/live/updated"}


def test_init_game_no_livestreams_no_extra_save(tmp_path: Path) -> None:
    """When no plugin writes livestreams, game.json is not re-saved."""
    info = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    game_dir, _ = init_game(tmp_path, info)

    state = load_game_state(game_dir)
    assert state.livestreams == {}


def test_create_events_emits_on_event_created(tmp_path: Path) -> None:
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    seg_dir = game_dir / "period-1"
    seg_dir.mkdir()
    f1 = seg_dir / "replay1.mkv"
    f2 = seg_dir / "replay2.mkv"
    f1.touch()
    f2.touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_EVENT_CREATED, emitted.append)

    create_events_for_segment([f1, f2], 1, game_dir)

    assert len(emitted) == 2
    assert all(ctx.hook is Hook.ON_EVENT_CREATED for ctx in emitted)
    assert "event" in emitted[0].data


def test_create_events_empty_no_hooks(tmp_path: Path) -> None:
    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_EVENT_CREATED, emitted.append)

    create_events_for_segment([], 1, tmp_path)
    assert len(emitted) == 0


def test_process_segment_emits_on_clip_available(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_CLIP_AVAILABLE, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_CLIP_AVAILABLE
    assert "output" in emitted[0].data
    assert "segment" in emitted[0].data


def test_process_segment_dry_run_no_clip_hook(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_CLIP_AVAILABLE, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    process_segment(game_dir, 1, ffmpeg_path=ffmpeg, dry_run=True)

    assert len(emitted) == 0


def test_merge_highlights_emits_on_highlights_merged(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_HIGHLIGHTS_MERGED, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_HIGHLIGHTS_MERGED
    assert "output" in emitted[0].data
    assert "segment_files" in emitted[0].data


def test_process_segment_emits_on_error_on_ffmpeg_failure(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_ERROR, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    fail_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="fail")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.core.ffmpeg.subprocess.run", return_value=fail_proc),
        pytest.raises(FFmpegError),
    ):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_ERROR
    assert emitted[0].data["operation"] == "process_segment"


def test_merge_highlights_emits_on_error_on_ffmpeg_failure(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_ERROR, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    fail_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="fail")
    from reeln.core.errors import FFmpegError

    with (
        patch("reeln.core.ffmpeg.subprocess.run", return_value=fail_proc),
        pytest.raises(FFmpegError),
    ):
        merge_game_highlights(game_dir, ffmpeg_path=ffmpeg)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_ERROR
    assert emitted[0].data["operation"] == "merge_game_highlights"


def test_process_segment_emits_on_segment_start(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_SEGMENT_START, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_SEGMENT_START
    assert emitted[0].data["game_dir"] == game_dir
    assert emitted[0].data["segment_number"] == 1
    assert emitted[0].data["segment_dir"] == seg_dir
    assert emitted[0].data["segment_alias"] == "period-1"


def test_process_segment_dry_run_no_segment_start_hook(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_SEGMENT_START, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    process_segment(game_dir, 1, ffmpeg_path=ffmpeg, dry_run=True)

    assert len(emitted) == 0


def test_process_segment_emits_on_segment_complete(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_SEGMENT_COMPLETE, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    with patch("reeln.core.ffmpeg.subprocess.run", return_value=_mock_ffmpeg_success()):
        process_segment(game_dir, 1, ffmpeg_path=ffmpeg)

    assert len(emitted) == 1
    assert emitted[0].hook is Hook.ON_SEGMENT_COMPLETE
    assert emitted[0].data["game_dir"] == game_dir
    assert emitted[0].data["segment_number"] == 1
    assert "output" in emitted[0].data
    assert emitted[0].data["events_created"] == 1


def test_process_segment_dry_run_no_segment_complete_hook(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    seg_dir = game_dir / "period-1"
    (seg_dir / "replay1.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_SEGMENT_COMPLETE, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    process_segment(game_dir, 1, ffmpeg_path=ffmpeg, dry_run=True)

    assert len(emitted) == 0


def test_merge_highlights_dry_run_no_hook(tmp_path: Path) -> None:
    game_dir = _make_game_dir(tmp_path)
    for i in range(1, 4):
        (tmp_path / f"period-{i}_2026-02-26.mkv").touch()

    emitted: list[HookContext] = []
    get_registry().register(Hook.ON_HIGHLIGHTS_MERGED, emitted.append)

    ffmpeg = Path("/usr/bin/ffmpeg")
    merge_game_highlights(game_dir, ffmpeg_path=ffmpeg, dry_run=True)

    assert len(emitted) == 0
