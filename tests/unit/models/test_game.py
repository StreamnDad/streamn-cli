"""Tests for game data models."""

from __future__ import annotations

from reeln.models.game import (
    GameEvent,
    GameInfo,
    GameState,
    RenderEntry,
    dict_to_game_event,
    dict_to_game_info,
    dict_to_game_state,
    dict_to_render_entry,
    game_event_to_dict,
    game_info_to_dict,
    game_state_to_dict,
    render_entry_to_dict,
)

# ---------------------------------------------------------------------------
# GameInfo
# ---------------------------------------------------------------------------


def test_game_info_required_fields() -> None:
    gi = GameInfo(date="2026-02-26", home_team="roseville", away_team="mahtomedi", sport="hockey")
    assert gi.date == "2026-02-26"
    assert gi.home_team == "roseville"
    assert gi.away_team == "mahtomedi"
    assert gi.sport == "hockey"


def test_game_info_defaults() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="generic")
    assert gi.game_number == 1
    assert gi.venue == ""
    assert gi.game_time == ""
    assert gi.period_length == 0
    assert gi.description == ""
    assert gi.thumbnail == ""


def test_game_info_custom_fields() -> None:
    gi = GameInfo(
        date="2026-03-01",
        home_team="lakers",
        away_team="celtics",
        sport="basketball",
        game_number=2,
        venue="Staples Center",
        game_time="7:00 PM",
        period_length=12,
    )
    assert gi.game_number == 2
    assert gi.venue == "Staples Center"
    assert gi.game_time == "7:00 PM"
    assert gi.period_length == 12


def test_game_info_with_description_and_thumbnail() -> None:
    gi = GameInfo(
        date="2026-03-04",
        home_team="eagles",
        away_team="hawks",
        sport="hockey",
        description="Big game tonight",
        thumbnail="/tmp/thumb.jpg",
    )
    assert gi.description == "Big game tonight"
    assert gi.thumbnail == "/tmp/thumb.jpg"


# ---------------------------------------------------------------------------
# RenderEntry
# ---------------------------------------------------------------------------


def test_render_entry_fields() -> None:
    entry = RenderEntry(
        input="period-1/clip.mkv",
        output="period-1/clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-02-26T12:00:00+00:00",
    )
    assert entry.input == "period-1/clip.mkv"
    assert entry.output == "period-1/clip_short.mp4"
    assert entry.segment_number == 1
    assert entry.format == "1080x1920"
    assert entry.crop_mode == "pad"
    assert entry.rendered_at == "2026-02-26T12:00:00+00:00"
    assert entry.event_id == ""


def test_render_entry_with_event_id() -> None:
    entry = RenderEntry(
        input="clip.mkv",
        output="clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-02-26T12:00:00+00:00",
        event_id="abc123",
    )
    assert entry.event_id == "abc123"


# ---------------------------------------------------------------------------
# GameEvent
# ---------------------------------------------------------------------------


def test_game_event_required_fields() -> None:
    ev = GameEvent(id="abc123", clip="period-1/Replay_001.mkv", segment_number=1)
    assert ev.id == "abc123"
    assert ev.clip == "period-1/Replay_001.mkv"
    assert ev.segment_number == 1


def test_game_event_defaults() -> None:
    ev = GameEvent(id="abc123", clip="clip.mkv", segment_number=1)
    assert ev.event_type == ""
    assert ev.player == ""
    assert ev.created_at == ""
    assert ev.metadata == {}


def test_game_event_custom_fields() -> None:
    ev = GameEvent(
        id="abc123",
        clip="period-1/Replay_001.mkv",
        segment_number=1,
        event_type="goal",
        player="#17",
        created_at="2026-02-28T18:00:00+00:00",
        metadata={"assists": ["#9", "#22"], "title": "Snipe from the slot"},
    )
    assert ev.event_type == "goal"
    assert ev.player == "#17"
    assert ev.created_at == "2026-02-28T18:00:00+00:00"
    assert ev.metadata["assists"] == ["#9", "#22"]
    assert ev.metadata["title"] == "Snipe from the slot"


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------


def test_game_state_defaults() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="generic")
    gs = GameState(game_info=gi)
    assert gs.segments_processed == []
    assert gs.highlighted is False
    assert gs.finished is False
    assert gs.created_at == ""
    assert gs.finished_at == ""
    assert gs.renders == []
    assert gs.events == []


def test_game_state_livestreams_default() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="generic")
    gs = GameState(game_info=gi)
    assert gs.livestreams == {}


def test_game_state_with_livestreams() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    gs = GameState(game_info=gi, livestreams={"google": "https://youtube.com/live/abc123"})
    assert gs.livestreams == {"google": "https://youtube.com/live/abc123"}


def test_game_state_custom() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    gs = GameState(
        game_info=gi,
        segments_processed=[1, 2],
        highlighted=True,
        finished=True,
        created_at="2026-02-26T12:00:00+00:00",
        finished_at="2026-02-26T14:00:00+00:00",
    )
    assert gs.segments_processed == [1, 2]
    assert gs.highlighted is True
    assert gs.finished is True
    assert gs.created_at == "2026-02-26T12:00:00+00:00"
    assert gs.finished_at == "2026-02-26T14:00:00+00:00"


def test_game_state_with_renders() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    entry = RenderEntry(
        input="clip.mkv",
        output="clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-02-26T12:00:00+00:00",
    )
    gs = GameState(game_info=gi, renders=[entry])
    assert len(gs.renders) == 1
    assert gs.renders[0].input == "clip.mkv"


def test_game_state_with_events() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    ev = GameEvent(id="abc123", clip="period-1/Replay_001.mkv", segment_number=1, event_type="goal")
    gs = GameState(game_info=gi, events=[ev])
    assert len(gs.events) == 1
    assert gs.events[0].event_type == "goal"


# ---------------------------------------------------------------------------
# Serialization: GameInfo
# ---------------------------------------------------------------------------


def test_game_info_to_dict() -> None:
    gi = GameInfo(
        date="2026-02-26",
        home_team="roseville",
        away_team="mahtomedi",
        sport="hockey",
        game_number=1,
        venue="OVAL",
    )
    d = game_info_to_dict(gi)
    assert d == {
        "date": "2026-02-26",
        "home_team": "roseville",
        "away_team": "mahtomedi",
        "sport": "hockey",
        "game_number": 1,
        "venue": "OVAL",
        "game_time": "",
        "period_length": 0,
        "description": "",
        "thumbnail": "",
    }


def test_game_info_to_dict_with_game_time() -> None:
    gi = GameInfo(
        date="2026-02-26",
        home_team="a",
        away_team="b",
        sport="hockey",
        game_time="7:00 PM",
    )
    d = game_info_to_dict(gi)
    assert d["game_time"] == "7:00 PM"


def test_dict_to_game_info() -> None:
    d = {
        "date": "2026-02-26",
        "home_team": "roseville",
        "away_team": "mahtomedi",
        "sport": "hockey",
        "game_number": 2,
        "venue": "OVAL",
    }
    gi = dict_to_game_info(d)
    assert gi.date == "2026-02-26"
    assert gi.home_team == "roseville"
    assert gi.away_team == "mahtomedi"
    assert gi.sport == "hockey"
    assert gi.game_number == 2
    assert gi.venue == "OVAL"


def test_dict_to_game_info_defaults() -> None:
    d = {"date": "2026-02-26", "home_team": "a", "away_team": "b", "sport": "generic"}
    gi = dict_to_game_info(d)
    assert gi.game_number == 1
    assert gi.venue == ""
    assert gi.game_time == ""
    assert gi.period_length == 0
    assert gi.description == ""
    assert gi.thumbnail == ""


def test_dict_to_game_info_legacy_rink_fallback() -> None:
    """Old game.json files with 'rink' key are read via backward-compat fallback."""
    d = {
        "date": "2026-02-26",
        "home_team": "a",
        "away_team": "b",
        "sport": "hockey",
        "rink": "OVAL",
    }
    gi = dict_to_game_info(d)
    assert gi.venue == "OVAL"


def test_dict_to_game_info_with_game_time() -> None:
    d = {
        "date": "2026-02-26",
        "home_team": "a",
        "away_team": "b",
        "sport": "hockey",
        "game_time": "7:00 PM",
    }
    gi = dict_to_game_info(d)
    assert gi.game_time == "7:00 PM"


def test_game_info_to_dict_with_period_length() -> None:
    gi = GameInfo(
        date="2026-02-26",
        home_team="a",
        away_team="b",
        sport="hockey",
        period_length=15,
    )
    d = game_info_to_dict(gi)
    assert d["period_length"] == 15


def test_dict_to_game_info_with_period_length() -> None:
    d = {
        "date": "2026-02-26",
        "home_team": "a",
        "away_team": "b",
        "sport": "hockey",
        "period_length": 12,
    }
    gi = dict_to_game_info(d)
    assert gi.period_length == 12


def test_game_info_to_dict_with_description_and_thumbnail() -> None:
    gi = GameInfo(
        date="2026-03-04",
        home_team="a",
        away_team="b",
        sport="hockey",
        description="Big game",
        thumbnail="/tmp/thumb.jpg",
    )
    d = game_info_to_dict(gi)
    assert d["description"] == "Big game"
    assert d["thumbnail"] == "/tmp/thumb.jpg"


def test_dict_to_game_info_with_description_and_thumbnail() -> None:
    d = {
        "date": "2026-03-04",
        "home_team": "a",
        "away_team": "b",
        "sport": "hockey",
        "description": "Big game",
        "thumbnail": "/tmp/thumb.jpg",
    }
    gi = dict_to_game_info(d)
    assert gi.description == "Big game"
    assert gi.thumbnail == "/tmp/thumb.jpg"


def test_game_info_round_trip() -> None:
    gi = GameInfo(
        date="2026-03-01",
        home_team="city",
        away_team="united",
        sport="soccer",
        game_number=3,
        venue="Stadium",
        game_time="3:00 PM",
        period_length=45,
        description="Championship match",
        thumbnail="/img/thumb.png",
    )
    assert dict_to_game_info(game_info_to_dict(gi)) == gi


# ---------------------------------------------------------------------------
# Serialization: RenderEntry
# ---------------------------------------------------------------------------


def test_render_entry_to_dict() -> None:
    entry = RenderEntry(
        input="clip.mkv",
        output="clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-02-26T12:00:00+00:00",
    )
    d = render_entry_to_dict(entry)
    assert d == {
        "input": "clip.mkv",
        "output": "clip_short.mp4",
        "segment_number": 1,
        "format": "1080x1920",
        "crop_mode": "pad",
        "rendered_at": "2026-02-26T12:00:00+00:00",
        "event_id": "",
    }


def test_render_entry_to_dict_with_event_id() -> None:
    entry = RenderEntry(
        input="clip.mkv",
        output="clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-02-26T12:00:00+00:00",
        event_id="abc123",
    )
    d = render_entry_to_dict(entry)
    assert d["event_id"] == "abc123"


def test_dict_to_render_entry() -> None:
    d = {
        "input": "clip.mkv",
        "output": "clip_short.mp4",
        "segment_number": 1,
        "format": "1080x1920",
        "crop_mode": "crop",
        "rendered_at": "2026-02-26T12:00:00+00:00",
    }
    entry = dict_to_render_entry(d)
    assert entry.input == "clip.mkv"
    assert entry.segment_number == 1
    assert entry.crop_mode == "crop"
    assert entry.event_id == ""


def test_dict_to_render_entry_with_event_id() -> None:
    d = {
        "input": "clip.mkv",
        "output": "clip_short.mp4",
        "segment_number": 1,
        "format": "1080x1920",
        "crop_mode": "pad",
        "rendered_at": "2026-02-26T12:00:00+00:00",
        "event_id": "abc123",
    }
    entry = dict_to_render_entry(d)
    assert entry.event_id == "abc123"


def test_render_entry_round_trip() -> None:
    entry = RenderEntry(
        input="p1/clip.mkv",
        output="p1/clip_short.mp4",
        segment_number=2,
        format="1080x1080",
        crop_mode="crop",
        rendered_at="2026-03-01T18:30:00+00:00",
    )
    assert dict_to_render_entry(render_entry_to_dict(entry)) == entry


def test_render_entry_round_trip_with_event_id() -> None:
    entry = RenderEntry(
        input="p1/clip.mkv",
        output="p1/clip_short.mp4",
        segment_number=2,
        format="1080x1080",
        crop_mode="crop",
        rendered_at="2026-03-01T18:30:00+00:00",
        event_id="def456",
    )
    assert dict_to_render_entry(render_entry_to_dict(entry)) == entry


# ---------------------------------------------------------------------------
# Serialization: GameEvent
# ---------------------------------------------------------------------------


def test_game_event_to_dict() -> None:
    ev = GameEvent(
        id="abc123",
        clip="period-1/Replay_001.mkv",
        segment_number=1,
        event_type="goal",
        player="#17",
        created_at="2026-02-28T18:00:00+00:00",
        metadata={"assists": ["#9"]},
    )
    d = game_event_to_dict(ev)
    assert d == {
        "id": "abc123",
        "clip": "period-1/Replay_001.mkv",
        "segment_number": 1,
        "event_type": "goal",
        "player": "#17",
        "created_at": "2026-02-28T18:00:00+00:00",
        "metadata": {"assists": ["#9"]},
    }


def test_game_event_to_dict_defaults() -> None:
    ev = GameEvent(id="abc123", clip="clip.mkv", segment_number=1)
    d = game_event_to_dict(ev)
    assert d["event_type"] == ""
    assert d["player"] == ""
    assert d["created_at"] == ""
    assert d["metadata"] == {}


def test_dict_to_game_event() -> None:
    d = {
        "id": "abc123",
        "clip": "period-1/Replay_001.mkv",
        "segment_number": 1,
        "event_type": "save",
        "player": "#35",
        "created_at": "2026-02-28T18:00:00+00:00",
        "metadata": {"description": "Great glove save"},
    }
    ev = dict_to_game_event(d)
    assert ev.id == "abc123"
    assert ev.clip == "period-1/Replay_001.mkv"
    assert ev.segment_number == 1
    assert ev.event_type == "save"
    assert ev.player == "#35"
    assert ev.metadata == {"description": "Great glove save"}


def test_dict_to_game_event_defaults() -> None:
    d = {"id": "abc123", "clip": "clip.mkv", "segment_number": 1}
    ev = dict_to_game_event(d)
    assert ev.event_type == ""
    assert ev.player == ""
    assert ev.created_at == ""
    assert ev.metadata == {}


def test_game_event_round_trip() -> None:
    ev = GameEvent(
        id="abc123",
        clip="period-2/Replay_003.mkv",
        segment_number=2,
        event_type="goal",
        player="#17",
        created_at="2026-02-28T18:30:00+00:00",
        metadata={"assists": ["#9", "#22"], "title": "Top shelf"},
    )
    assert dict_to_game_event(game_event_to_dict(ev)) == ev


# ---------------------------------------------------------------------------
# Serialization: GameState
# ---------------------------------------------------------------------------


def test_game_state_to_dict() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    gs = GameState(
        game_info=gi,
        segments_processed=[1, 2],
        highlighted=True,
        finished=False,
        created_at="2026-02-26T12:00:00+00:00",
    )
    d = game_state_to_dict(gs)
    assert d["game_info"]["home_team"] == "a"
    assert d["segments_processed"] == [1, 2]
    assert d["highlighted"] is True
    assert d["finished"] is False
    assert d["created_at"] == "2026-02-26T12:00:00+00:00"
    assert d["finished_at"] == ""
    assert d["renders"] == []
    assert d["events"] == []


def test_game_state_to_dict_with_livestreams() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    gs = GameState(game_info=gi, livestreams={"google": "https://youtube.com/live/abc123"})
    d = game_state_to_dict(gs)
    assert d["livestreams"] == {"google": "https://youtube.com/live/abc123"}


def test_game_state_to_dict_livestreams_empty() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    gs = GameState(game_info=gi)
    d = game_state_to_dict(gs)
    assert d["livestreams"] == {}


def test_game_state_to_dict_with_finished_at() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    gs = GameState(
        game_info=gi,
        finished=True,
        finished_at="2026-02-26T14:00:00+00:00",
    )
    d = game_state_to_dict(gs)
    assert d["finished"] is True
    assert d["finished_at"] == "2026-02-26T14:00:00+00:00"


def test_game_state_to_dict_with_renders() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    entry = RenderEntry(
        input="clip.mkv",
        output="clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-02-26T12:00:00+00:00",
    )
    gs = GameState(game_info=gi, renders=[entry])
    d = game_state_to_dict(gs)
    assert len(d["renders"]) == 1
    assert d["renders"][0]["input"] == "clip.mkv"


def test_game_state_to_dict_with_events() -> None:
    gi = GameInfo(date="2026-02-26", home_team="a", away_team="b", sport="hockey")
    ev = GameEvent(id="abc123", clip="period-1/Replay_001.mkv", segment_number=1, event_type="goal")
    gs = GameState(game_info=gi, events=[ev])
    d = game_state_to_dict(gs)
    assert len(d["events"]) == 1
    assert d["events"][0]["id"] == "abc123"
    assert d["events"][0]["event_type"] == "goal"


def test_dict_to_game_state() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
        "segments_processed": [1],
        "highlighted": False,
        "finished": False,
        "created_at": "2026-02-26T12:00:00+00:00",
    }
    gs = dict_to_game_state(d)
    assert gs.game_info.sport == "generic"
    assert gs.segments_processed == [1]
    assert gs.created_at == "2026-02-26T12:00:00+00:00"
    assert gs.renders == []
    assert gs.events == []


def test_dict_to_game_state_defaults() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
    }
    gs = dict_to_game_state(d)
    assert gs.segments_processed == []
    assert gs.highlighted is False
    assert gs.finished is False
    assert gs.created_at == ""
    assert gs.finished_at == ""
    assert gs.renders == []
    assert gs.events == []


def test_dict_to_game_state_with_livestreams() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
        "livestreams": {"google": "https://youtube.com/live/abc123"},
    }
    gs = dict_to_game_state(d)
    assert gs.livestreams == {"google": "https://youtube.com/live/abc123"}


def test_dict_to_game_state_livestreams_missing() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
    }
    gs = dict_to_game_state(d)
    assert gs.livestreams == {}


def test_dict_to_game_state_with_finished_at() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
        "finished": True,
        "finished_at": "2026-02-26T14:00:00+00:00",
    }
    gs = dict_to_game_state(d)
    assert gs.finished is True
    assert gs.finished_at == "2026-02-26T14:00:00+00:00"


def test_dict_to_game_state_with_renders() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
        "renders": [
            {
                "input": "clip.mkv",
                "output": "clip_short.mp4",
                "segment_number": 1,
                "format": "1080x1920",
                "crop_mode": "pad",
                "rendered_at": "2026-02-26T12:00:00+00:00",
            },
        ],
    }
    gs = dict_to_game_state(d)
    assert len(gs.renders) == 1
    assert gs.renders[0].input == "clip.mkv"


def test_dict_to_game_state_with_events() -> None:
    d = {
        "game_info": {
            "date": "2026-02-26",
            "home_team": "a",
            "away_team": "b",
            "sport": "generic",
        },
        "events": [
            {
                "id": "abc123",
                "clip": "period-1/Replay_001.mkv",
                "segment_number": 1,
                "event_type": "goal",
                "player": "#17",
                "created_at": "2026-02-26T18:00:00+00:00",
                "metadata": {"assists": ["#9"]},
            },
        ],
    }
    gs = dict_to_game_state(d)
    assert len(gs.events) == 1
    assert gs.events[0].id == "abc123"
    assert gs.events[0].event_type == "goal"
    assert gs.events[0].metadata == {"assists": ["#9"]}


def test_game_state_round_trip() -> None:
    gi = GameInfo(
        date="2026-03-01",
        home_team="x",
        away_team="y",
        sport="basketball",
        game_number=2,
        venue="Arena",
    )
    entry = RenderEntry(
        input="q1/clip.mkv",
        output="q1/clip_short.mp4",
        segment_number=1,
        format="1080x1920",
        crop_mode="pad",
        rendered_at="2026-03-01T18:30:00+00:00",
    )
    ev = GameEvent(
        id="abc123",
        clip="q1/Replay_001.mkv",
        segment_number=1,
        event_type="goal",
        player="#17",
        created_at="2026-03-01T18:20:00+00:00",
        metadata={"assists": ["#9"]},
    )
    gs = GameState(
        game_info=gi,
        segments_processed=[1, 2, 3],
        highlighted=True,
        finished=True,
        created_at="2026-03-01T18:30:00+00:00",
        finished_at="2026-03-01T20:00:00+00:00",
        renders=[entry],
        events=[ev],
        livestreams={"google": "https://youtube.com/live/abc123"},
    )
    assert dict_to_game_state(game_state_to_dict(gs)) == gs
