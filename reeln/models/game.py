"""Game data models: GameInfo, GameEvent, RenderEntry, and GameState."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GameInfo:
    """Metadata describing a game."""

    date: str
    home_team: str
    away_team: str
    sport: str
    game_number: int = 1
    venue: str = ""
    game_time: str = ""
    period_length: int = 0
    description: str = ""
    thumbnail: str = ""


@dataclass
class GameEvent:
    """A notable event captured during a game segment."""

    id: str
    clip: str
    segment_number: int
    event_type: str = ""
    player: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderEntry:
    """Record of a rendered short within a game directory."""

    input: str
    output: str
    segment_number: int
    format: str
    crop_mode: str
    rendered_at: str
    event_id: str = ""


@dataclass
class GameState:
    """Mutable state tracking a game's lifecycle."""

    game_info: GameInfo
    segments_processed: list[int] = field(default_factory=list)
    highlighted: bool = False
    finished: bool = False
    created_at: str = ""
    finished_at: str = ""
    renders: list[RenderEntry] = field(default_factory=list)
    events: list[GameEvent] = field(default_factory=list)
    livestreams: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def game_info_to_dict(info: GameInfo) -> dict[str, Any]:
    """Serialize a ``GameInfo`` to a JSON-compatible dict."""
    return {
        "date": info.date,
        "home_team": info.home_team,
        "away_team": info.away_team,
        "sport": info.sport,
        "game_number": info.game_number,
        "venue": info.venue,
        "game_time": info.game_time,
        "period_length": info.period_length,
        "description": info.description,
        "thumbnail": info.thumbnail,
    }


def dict_to_game_info(data: dict[str, Any]) -> GameInfo:
    """Deserialize a dict into a ``GameInfo``."""
    return GameInfo(
        date=str(data["date"]),
        home_team=str(data["home_team"]),
        away_team=str(data["away_team"]),
        sport=str(data["sport"]),
        game_number=int(data.get("game_number", 1)),
        venue=str(data.get("venue", data.get("rink", ""))),
        game_time=str(data.get("game_time", "")),
        period_length=int(data.get("period_length", 0)),
        description=str(data.get("description", "")),
        thumbnail=str(data.get("thumbnail", "")),
    )


def game_event_to_dict(event: GameEvent) -> dict[str, Any]:
    """Serialize a ``GameEvent`` to a JSON-compatible dict."""
    return {
        "id": event.id,
        "clip": event.clip,
        "segment_number": event.segment_number,
        "event_type": event.event_type,
        "player": event.player,
        "created_at": event.created_at,
        "metadata": dict(event.metadata),
    }


def dict_to_game_event(data: dict[str, Any]) -> GameEvent:
    """Deserialize a dict into a ``GameEvent``."""
    return GameEvent(
        id=str(data["id"]),
        clip=str(data["clip"]),
        segment_number=int(data["segment_number"]),
        event_type=str(data.get("event_type", "")),
        player=str(data.get("player", "")),
        created_at=str(data.get("created_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def render_entry_to_dict(entry: RenderEntry) -> dict[str, Any]:
    """Serialize a ``RenderEntry`` to a JSON-compatible dict."""
    return {
        "input": entry.input,
        "output": entry.output,
        "segment_number": entry.segment_number,
        "format": entry.format,
        "crop_mode": entry.crop_mode,
        "rendered_at": entry.rendered_at,
        "event_id": entry.event_id,
    }


def dict_to_render_entry(data: dict[str, Any]) -> RenderEntry:
    """Deserialize a dict into a ``RenderEntry``."""
    return RenderEntry(
        input=str(data["input"]),
        output=str(data["output"]),
        segment_number=int(data["segment_number"]),
        format=str(data["format"]),
        crop_mode=str(data["crop_mode"]),
        rendered_at=str(data["rendered_at"]),
        event_id=str(data.get("event_id", "")),
    )


def game_state_to_dict(state: GameState) -> dict[str, Any]:
    """Serialize a ``GameState`` to a JSON-compatible dict."""
    return {
        "game_info": game_info_to_dict(state.game_info),
        "segments_processed": list(state.segments_processed),
        "highlighted": state.highlighted,
        "finished": state.finished,
        "created_at": state.created_at,
        "finished_at": state.finished_at,
        "renders": [render_entry_to_dict(r) for r in state.renders],
        "events": [game_event_to_dict(e) for e in state.events],
        "livestreams": dict(state.livestreams),
    }


def dict_to_game_state(data: dict[str, Any]) -> GameState:
    """Deserialize a dict into a ``GameState``."""
    renders_raw = data.get("renders", [])
    events_raw = data.get("events", [])
    return GameState(
        game_info=dict_to_game_info(data["game_info"]),
        segments_processed=list(data.get("segments_processed", [])),
        highlighted=bool(data.get("highlighted", False)),
        finished=bool(data.get("finished", False)),
        created_at=str(data.get("created_at", "")),
        finished_at=str(data.get("finished_at", "")),
        renders=[dict_to_render_entry(r) for r in renders_raw],
        events=[dict_to_game_event(e) for e in events_raw],
        livestreams=dict(data.get("livestreams", {})),
    )
