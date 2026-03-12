"""Tests for plugin discovery, capability detection, and loading."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from reeln.core.errors import PluginError
from reeln.models.config import PluginsConfig
from reeln.models.plugin import GeneratorResult
from reeln.plugins.hooks import Hook, HookContext
from reeln.plugins.loader import (
    _detect_capabilities,
    _register_plugin_hooks,
    activate_plugins,
    discover_plugins,
    load_enabled_plugins,
    load_plugin,
)
from reeln.plugins.registry import HookRegistry, get_registry, reset_registry

# ---------------------------------------------------------------------------
# Helpers — stub plugins
# ---------------------------------------------------------------------------


class _FullPlugin:
    name = "full"

    def generate(self, context: dict[str, Any]) -> GeneratorResult:
        return GeneratorResult()

    def enrich(self, event_data: dict[str, Any]) -> dict[str, Any]:
        return event_data

    def upload(self, path: Path, *, metadata: dict[str, Any] | None = None) -> str:
        return "https://example.com"

    def notify(self, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        pass


class _UploaderOnly:
    name = "uploader"

    def upload(self, path: Path, *, metadata: dict[str, Any] | None = None) -> str:
        return "url"


class _NoCaps:
    name = "nocaps"


class _ConfigPlugin:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config


class _NoConfigPlugin:
    def __init__(self) -> None:
        pass


def _make_entry_point(name: str, cls: type) -> MagicMock:
    ep = MagicMock()
    ep.name = name
    ep.value = f"test_module:{cls.__name__}"
    ep.load.return_value = cls
    return ep


# ---------------------------------------------------------------------------
# _detect_capabilities
# ---------------------------------------------------------------------------


def test_detect_capabilities_all() -> None:
    caps = _detect_capabilities(_FullPlugin())
    assert set(caps) == {"generator", "enricher", "uploader", "notifier"}


def test_detect_capabilities_partial() -> None:
    caps = _detect_capabilities(_UploaderOnly())
    assert caps == ["uploader"]


def test_detect_capabilities_none() -> None:
    caps = _detect_capabilities(_NoCaps())
    assert caps == []


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


def test_discover_empty() -> None:
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[]):
        result = discover_plugins()
    assert result == []


def test_discover_with_entries() -> None:
    ep1 = _make_entry_point("youtube", _UploaderOnly)
    ep2 = _make_entry_point("llm", _NoCaps)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep1, ep2]):
        result = discover_plugins()

    assert len(result) == 2
    assert result[0].name == "youtube"
    assert result[1].name == "llm"
    assert result[0].enabled is False


def test_discover_with_no_dist() -> None:
    """Entry points with dist=None still produce a PluginInfo with empty package."""
    ep = MagicMock()
    ep.name = "nodist"
    ep.value = "test:NoDist"
    ep.dist = None
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        result = discover_plugins()
    assert len(result) == 1
    assert result[0].name == "nodist"
    assert result[0].package == ""


def test_discover_handles_exception() -> None:
    with patch(
        "reeln.plugins.loader.importlib.metadata.entry_points",
        side_effect=Exception("broken"),
    ):
        result = discover_plugins()
    assert result == []


# ---------------------------------------------------------------------------
# load_plugin
# ---------------------------------------------------------------------------


def test_load_plugin_success() -> None:
    ep = _make_entry_point("test", _NoConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        plugin = load_plugin("test")
    assert isinstance(plugin, _NoConfigPlugin)


def test_load_plugin_with_config() -> None:
    ep = _make_entry_point("test", _ConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        plugin = load_plugin("test", config={"key": "value"})
    assert isinstance(plugin, _ConfigPlugin)
    assert plugin.config == {"key": "value"}  # type: ignore[union-attr]


def test_load_plugin_config_not_accepted() -> None:
    """Plugin that doesn't accept config args falls back to no-arg init."""
    ep = _make_entry_point("test", _NoConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        plugin = load_plugin("test", config={"key": "value"})
    assert isinstance(plugin, _NoConfigPlugin)


def test_load_plugin_not_found() -> None:
    with (
        patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[]),
        pytest.raises(PluginError, match="Plugin not found"),
    ):
        load_plugin("nonexistent")


def test_load_plugin_load_failure() -> None:
    ep = MagicMock()
    ep.name = "broken"
    ep.load.side_effect = ImportError("module not found")
    with (
        patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]),
        pytest.raises(PluginError, match="Failed to load"),
    ):
        load_plugin("broken")


def test_load_plugin_instantiation_failure() -> None:
    class _BadPlugin:
        def __init__(self) -> None:
            raise RuntimeError("init failed")

    ep = _make_entry_point("bad", _BadPlugin)
    with (
        patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]),
        pytest.raises(PluginError, match="Failed to instantiate"),
    ):
        load_plugin("bad")


def test_load_plugin_entry_points_failure() -> None:
    with (
        patch(
            "reeln.plugins.loader.importlib.metadata.entry_points",
            side_effect=Exception("broken"),
        ),
        pytest.raises(PluginError, match="Failed to read"),
    ):
        load_plugin("test")


# ---------------------------------------------------------------------------
# load_enabled_plugins
# ---------------------------------------------------------------------------


def test_load_enabled_plugins_empty() -> None:
    with patch("reeln.plugins.loader.discover_plugins", return_value=[]):
        result = load_enabled_plugins([], [])
    assert result == {}


def test_load_enabled_plugins_filter_disabled() -> None:
    ep1 = _make_entry_point("youtube", _NoConfigPlugin)
    ep2 = _make_entry_point("llm", _NoConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep1, ep2]):
        result = load_enabled_plugins(["youtube", "llm"], ["llm"])
    assert "youtube" in result
    assert "llm" not in result


def test_load_enabled_plugins_filter_by_enabled_list() -> None:
    ep1 = _make_entry_point("youtube", _NoConfigPlugin)
    ep2 = _make_entry_point("llm", _NoConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep1, ep2]):
        result = load_enabled_plugins(["youtube"], [])
    assert "youtube" in result
    assert "llm" not in result


def test_load_enabled_plugins_all_discovered_when_no_enabled_list() -> None:
    from reeln.models.plugin import PluginInfo

    ep1 = _make_entry_point("youtube", _NoConfigPlugin)
    discovered = [PluginInfo(name="youtube", entry_point="test:Cls")]
    with (
        patch("reeln.plugins.loader.discover_plugins", return_value=discovered),
        patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep1]),
    ):
        result = load_enabled_plugins([], [])
    assert "youtube" in result


def test_load_enabled_plugins_error_continues() -> None:
    """A plugin that fails to load doesn't prevent others from loading."""
    ep_good = _make_entry_point("good", _NoConfigPlugin)
    ep_bad = MagicMock()
    ep_bad.name = "bad"
    ep_bad.load.side_effect = ImportError("broken")

    with patch(
        "reeln.plugins.loader.importlib.metadata.entry_points",
        return_value=[ep_good, ep_bad],
    ):
        result = load_enabled_plugins(["good", "bad"], [])

    assert "good" in result
    assert "bad" not in result


def test_load_enabled_plugins_not_installed_logs_debug(caplog: pytest.LogCaptureFixture) -> None:
    """Plugins that are not installed (no entry point) log at debug, not warning."""
    with (
        patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[]),
        caplog.at_level(logging.DEBUG, logger="reeln.plugins.loader"),
    ):
        result = load_enabled_plugins(["missing"], [])

    assert "missing" not in result
    # Should appear in debug log, not warning
    assert any(
        "not installed" in r.message and r.levelno == logging.DEBUG
        for r in caplog.records
    )


def test_load_enabled_plugins_with_settings() -> None:
    ep = _make_entry_point("test", _ConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        result = load_enabled_plugins(["test"], [], settings={"test": {"api_key": "test123"}})
    assert "test" in result
    assert result["test"].config == {"api_key": "test123"}  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# _register_plugin_hooks / activate_plugins
# ---------------------------------------------------------------------------


class _ExplicitRegisterPlugin:
    """Plugin that has a register() method for explicit hook registration."""

    def __init__(self) -> None:
        self.registered = False

    def register(self, registry: HookRegistry) -> None:
        self.registered = True
        registry.register(Hook.ON_GAME_INIT, self._on_game_init)

    def _on_game_init(self, context: HookContext) -> None:
        pass  # pragma: no cover

    def on_game_finish(self, context: HookContext) -> None:
        """Should NOT be auto-discovered because register() takes precedence."""


class _AutoDiscoverPlugin:
    """Plugin with on_<hook> methods but no register()."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_game_init(self, context: HookContext) -> None:
        self.calls.append("on_game_init")

    def on_pre_render(self, context: HookContext) -> None:
        self.calls.append("on_pre_render")


class _BrokenRegisterPlugin:
    """Plugin whose register() raises an exception."""

    def register(self, registry: HookRegistry) -> None:
        raise RuntimeError("register exploded")


class _NoHooksPlugin:
    """Plugin with no register() and no on_<hook> methods."""

    pass


def test_register_plugin_hooks_explicit() -> None:
    """register() method is called and hooks are wired."""
    registry = HookRegistry()
    plugin = _ExplicitRegisterPlugin()
    _register_plugin_hooks("explicit", plugin, registry)

    assert plugin.registered is True
    assert registry.has_handlers(Hook.ON_GAME_INIT)
    # on_game_finish should NOT be auto-discovered
    assert not registry.has_handlers(Hook.ON_GAME_FINISH)


def test_register_plugin_hooks_auto_discover() -> None:
    """on_<hook> methods are auto-discovered when no register()."""
    registry = HookRegistry()
    plugin = _AutoDiscoverPlugin()
    _register_plugin_hooks("auto", plugin, registry)

    assert registry.has_handlers(Hook.ON_GAME_INIT)
    assert registry.has_handlers(Hook.PRE_RENDER)
    assert not registry.has_handlers(Hook.ON_ERROR)


def test_register_takes_precedence_over_auto_discover() -> None:
    """register() takes precedence — auto-discovery is skipped entirely."""
    registry = HookRegistry()
    plugin = _ExplicitRegisterPlugin()
    _register_plugin_hooks("explicit", plugin, registry)

    # register() wires ON_GAME_INIT but NOT ON_GAME_FINISH
    assert registry.has_handlers(Hook.ON_GAME_INIT)
    assert not registry.has_handlers(Hook.ON_GAME_FINISH)


def test_register_failure_logged_not_raised() -> None:
    """register() failure is logged, not raised — plugin crash doesn't break CLI."""
    registry = HookRegistry()
    plugin = _BrokenRegisterPlugin()
    # Should not raise
    _register_plugin_hooks("broken", plugin, registry)
    # Nothing should be registered
    assert not registry.has_handlers(Hook.ON_GAME_INIT)


def test_no_hooks_plugin_registers_nothing() -> None:
    """Plugin with no hooks registers nothing."""
    registry = HookRegistry()
    plugin = _NoHooksPlugin()
    _register_plugin_hooks("nohooks", plugin, registry)

    for hook in Hook:
        assert not registry.has_handlers(hook)


def test_activate_plugins_returns_loaded_dict() -> None:
    """activate_plugins returns the loaded plugins dict."""
    ep = _make_entry_point("test", _NoConfigPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        result = activate_plugins(PluginsConfig(enabled=["test"]))

    assert "test" in result
    assert isinstance(result["test"], _NoConfigPlugin)
    reset_registry()


def test_activate_plugins_empty_config() -> None:
    """Empty config returns empty dict."""
    with patch("reeln.plugins.loader.discover_plugins", return_value=[]):
        result = activate_plugins(PluginsConfig())

    assert result == {}
    reset_registry()


def test_activate_plugins_idempotent() -> None:
    """Double activation doesn't double-register handlers."""
    ep = _make_entry_point("auto", _AutoDiscoverPlugin)
    with patch("reeln.plugins.loader.importlib.metadata.entry_points", return_value=[ep]):
        activate_plugins(PluginsConfig(enabled=["auto"]))
        activate_plugins(PluginsConfig(enabled=["auto"]))

    registry = get_registry()
    # ON_GAME_INIT should have exactly 1 handler, not 2
    handlers = registry._handlers.get(Hook.ON_GAME_INIT, [])
    assert len(handlers) == 1
    reset_registry()
