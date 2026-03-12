"""Hook enum, context, and handler protocol for the plugin system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class Hook(Enum):
    """Lifecycle hooks emitted by core operations."""

    PRE_RENDER = "pre_render"
    POST_RENDER = "post_render"
    ON_CLIP_AVAILABLE = "on_clip_available"
    ON_EVENT_CREATED = "on_event_created"
    ON_EVENT_TAGGED = "on_event_tagged"
    ON_GAME_INIT = "on_game_init"
    ON_GAME_READY = "on_game_ready"
    ON_GAME_FINISH = "on_game_finish"
    ON_HIGHLIGHTS_MERGED = "on_highlights_merged"
    ON_SEGMENT_START = "on_segment_start"
    ON_SEGMENT_COMPLETE = "on_segment_complete"
    ON_ERROR = "on_error"


@dataclass(frozen=True)
class HookContext:
    """Data passed to hook handlers when a hook is emitted."""

    hook: Hook
    data: dict[str, Any] = field(default_factory=dict)
    shared: dict[str, Any] = field(default_factory=dict)


class HookHandler(Protocol):
    """Callable protocol for hook handlers."""

    def __call__(self, context: HookContext) -> None: ...  # pragma: no cover
