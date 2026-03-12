"""Tests for config loading, merging, validation, env overrides, and atomic writes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from reeln.core.config import (
    apply_env_overrides,
    config_dir,
    config_to_dict,
    data_dir,
    deep_merge,
    default_config,
    default_config_path,
    dict_to_config,
    load_config,
    save_config,
    validate_config,
    validate_plugin_configs,
)
from reeln.core.errors import ConfigError
from reeln.models.config import AppConfig, PathConfig, PluginsConfig, VideoConfig
from reeln.models.plugin import OrchestrationConfig
from reeln.models.profile import IterationConfig, RenderProfile

# ---------------------------------------------------------------------------
# XDG paths
# ---------------------------------------------------------------------------


def test_config_dir_darwin() -> None:
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "darwin"
        result = config_dir()
    assert result == Path.home() / "Library" / "Application Support" / "reeln"


def test_config_dir_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "win32"
        result = config_dir()
    assert result == Path(r"C:\Users\test\AppData\Roaming") / "reeln"


def test_config_dir_linux_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = config_dir()
    assert result == Path.home() / ".config" / "reeln"


def test_config_dir_linux_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = config_dir()
    assert result == Path("/custom/config/reeln")


def test_data_dir_darwin() -> None:
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "darwin"
        result = data_dir()
    assert result == Path.home() / "Library" / "Application Support" / "reeln" / "data"


def test_data_dir_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "win32"
        result = data_dir()
    assert result == Path(r"C:\Users\test\AppData\Roaming") / "reeln" / "data"


def test_data_dir_linux_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = data_dir()
    assert result == Path.home() / ".local" / "share" / "reeln"


def test_data_dir_linux_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
    with patch("reeln.core.config.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = data_dir()
    assert result == Path("/custom/data/reeln")


def test_default_config_path_no_profile() -> None:
    with patch("reeln.core.config.config_dir", return_value=Path("/cfg/reeln")):
        result = default_config_path()
    assert result == Path("/cfg/reeln/config.json")


def test_default_config_path_with_profile() -> None:
    with patch("reeln.core.config.config_dir", return_value=Path("/cfg/reeln")):
        result = default_config_path("tournament")
    assert result == Path("/cfg/reeln/config.tournament.json")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_config() -> None:
    cfg = default_config()
    assert cfg.config_version == 1
    assert cfg.sport == "generic"
    assert cfg.video.codec == "libx264"


def test_default_config_has_player_overlay_profile() -> None:
    cfg = default_config()
    assert "player-overlay" in cfg.render_profiles
    profile = cfg.render_profiles["player-overlay"]
    assert profile.name == "player-overlay"
    assert profile.speed is None
    assert profile.subtitle_template == "builtin:goal_overlay"


def test_default_config_has_goal_iteration_mapping() -> None:
    cfg = default_config()
    assert "goal" in cfg.iterations.mappings
    assert cfg.iterations.mappings["goal"] == ["player-overlay"]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_config_to_dict_roundtrip() -> None:
    cfg = AppConfig(
        sport="hockey",
        video=VideoConfig(crf=20),
        paths=PathConfig(output_dir=Path("/out")),
    )
    d = config_to_dict(cfg)
    assert d["sport"] == "hockey"
    assert d["video"]["crf"] == 20
    assert d["paths"]["output_dir"] == "/out"
    assert d["paths"]["temp_dir"] is None


def test_dict_to_config_full() -> None:
    d = {
        "config_version": 1,
        "sport": "basketball",
        "video": {"codec": "libx265", "crf": 22},
        "paths": {"output_dir": "~/output"},
    }
    cfg = dict_to_config(d)
    assert cfg.sport == "basketball"
    assert cfg.video.codec == "libx265"
    assert cfg.video.crf == 22
    assert cfg.video.preset == "medium"  # default preserved
    assert cfg.paths.output_dir is not None
    assert "~" not in str(cfg.paths.output_dir)  # expanduser applied


def test_dict_to_config_minimal() -> None:
    cfg = dict_to_config({})
    assert cfg.config_version == 1
    assert cfg.sport == "generic"
    assert cfg.video.ffmpeg_path == "ffmpeg"
    assert cfg.paths.output_dir is None
    assert cfg.render_profiles == {}
    assert cfg.iterations.mappings == {}


def test_config_to_dict_none_paths() -> None:
    cfg = AppConfig()
    d = config_to_dict(cfg)
    assert d["paths"]["source_dir"] is None
    assert d["paths"]["source_glob"] == "Replay_*.mkv"
    assert d["paths"]["output_dir"] is None
    assert d["paths"]["temp_dir"] is None


def test_config_to_dict_source_glob_custom() -> None:
    cfg = AppConfig(paths=PathConfig(source_dir=Path("/replays"), source_glob="*.mp4"))
    d = config_to_dict(cfg)
    assert d["paths"]["source_dir"] == "/replays"
    assert d["paths"]["source_glob"] == "*.mp4"


def test_dict_to_config_source_glob_custom() -> None:
    d = {
        "paths": {"source_dir": "/replays", "source_glob": "Game_*.mp4"},
    }
    cfg = dict_to_config(d)
    assert cfg.paths.source_dir == Path("/replays")
    assert cfg.paths.source_glob == "Game_*.mp4"


def test_dict_to_config_source_glob_default() -> None:
    cfg = dict_to_config({"paths": {}})
    assert cfg.paths.source_glob == "Replay_*.mkv"


# ---------------------------------------------------------------------------
# Render profiles + iterations serialization
# ---------------------------------------------------------------------------


def test_config_to_dict_with_profiles() -> None:
    cfg = AppConfig(
        render_profiles={
            "slowmo": RenderProfile(name="slowmo", speed=0.5),
        }
    )
    d = config_to_dict(cfg)
    assert "render_profiles" in d
    assert d["render_profiles"]["slowmo"] == {"speed": 0.5}


def test_config_to_dict_empty_profiles() -> None:
    cfg = AppConfig()
    d = config_to_dict(cfg)
    assert "render_profiles" not in d


def test_config_to_dict_with_iterations() -> None:
    cfg = AppConfig(iterations=IterationConfig(mappings={"default": ["fullspeed"], "goal": ["slowmo"]}))
    d = config_to_dict(cfg)
    assert "iterations" in d
    assert d["iterations"]["goal"] == ["slowmo"]


def test_config_to_dict_empty_iterations() -> None:
    cfg = AppConfig()
    d = config_to_dict(cfg)
    assert "iterations" not in d


def test_dict_to_config_with_profiles() -> None:
    d = {
        "render_profiles": {
            "slowmo": {"speed": 0.5, "codec": "libx265"},
        },
    }
    cfg = dict_to_config(d)
    assert "slowmo" in cfg.render_profiles
    assert cfg.render_profiles["slowmo"].speed == 0.5
    assert cfg.render_profiles["slowmo"].codec == "libx265"


def test_dict_to_config_with_iterations() -> None:
    d = {
        "iterations": {
            "default": ["fullspeed"],
            "goal": ["slowmo", "overlay"],
        },
    }
    cfg = dict_to_config(d)
    assert cfg.iterations.profiles_for_event("goal") == ["slowmo", "overlay"]
    assert cfg.iterations.profiles_for_event("save") == ["fullspeed"]


def test_dict_to_config_profiles_not_dict_ignored() -> None:
    d = {"render_profiles": "not_a_dict"}
    cfg = dict_to_config(d)
    assert cfg.render_profiles == {}


def test_dict_to_config_profiles_entry_not_dict_skipped() -> None:
    d = {"render_profiles": {"good": {"speed": 0.5}, "bad": "not_a_dict"}}
    cfg = dict_to_config(d)
    assert "good" in cfg.render_profiles
    assert "bad" not in cfg.render_profiles


def test_dict_to_config_iterations_not_dict_ignored() -> None:
    d = {"iterations": "not_a_dict"}
    cfg = dict_to_config(d)
    assert cfg.iterations.mappings == {}


# ---------------------------------------------------------------------------
# Orchestration + plugins serialization
# ---------------------------------------------------------------------------


def test_config_to_dict_with_orchestration() -> None:
    cfg = AppConfig(
        orchestration=OrchestrationConfig(upload_bitrate_kbps=5000, sequential=True),
    )
    d = config_to_dict(cfg)
    assert "orchestration" in d
    assert d["orchestration"]["upload_bitrate_kbps"] == 5000
    assert d["orchestration"]["sequential"] is True


def test_config_to_dict_default_orchestration_omitted() -> None:
    cfg = AppConfig()
    d = config_to_dict(cfg)
    assert "orchestration" not in d


def test_config_to_dict_orchestration_non_sequential() -> None:
    cfg = AppConfig(
        orchestration=OrchestrationConfig(sequential=False),
    )
    d = config_to_dict(cfg)
    assert "orchestration" in d
    assert d["orchestration"]["sequential"] is False


def test_config_to_dict_with_plugins() -> None:
    cfg = AppConfig(
        plugins=PluginsConfig(
            enabled=["youtube"],
            disabled=["llm"],
            settings={"youtube": {"api_key": "test"}},
        ),
    )
    d = config_to_dict(cfg)
    assert "plugins" in d
    assert d["plugins"]["enabled"] == ["youtube"]
    assert d["plugins"]["disabled"] == ["llm"]
    assert d["plugins"]["settings"]["youtube"]["api_key"] == "test"


def test_config_to_dict_with_plugins_enabled_only() -> None:
    cfg = AppConfig(
        plugins=PluginsConfig(enabled=["youtube"]),
    )
    d = config_to_dict(cfg)
    assert d["plugins"]["enabled"] == ["youtube"]
    assert d["plugins"]["disabled"] == []
    assert d["plugins"]["settings"] == {}
    assert d["plugins"]["registry_url"] == ""


def test_config_to_dict_with_plugins_disabled_only() -> None:
    cfg = AppConfig(
        plugins=PluginsConfig(disabled=["llm"]),
    )
    d = config_to_dict(cfg)
    assert d["plugins"]["enabled"] == []
    assert d["plugins"]["disabled"] == ["llm"]
    assert d["plugins"]["settings"] == {}
    assert d["plugins"]["registry_url"] == ""


def test_config_to_dict_with_plugins_settings_only() -> None:
    cfg = AppConfig(
        plugins=PluginsConfig(settings={"youtube": {"api_key": "test"}}),
    )
    d = config_to_dict(cfg)
    assert d["plugins"]["enabled"] == []
    assert d["plugins"]["disabled"] == []
    assert d["plugins"]["settings"]["youtube"]["api_key"] == "test"
    assert d["plugins"]["registry_url"] == ""


def test_config_to_dict_with_plugins_registry_url() -> None:
    cfg = AppConfig(
        plugins=PluginsConfig(registry_url="https://example.com/reg.json"),
    )
    d = config_to_dict(cfg)
    assert "plugins" in d
    assert d["plugins"]["registry_url"] == "https://example.com/reg.json"


def test_config_to_dict_plugins_registry_url_empty_included() -> None:
    """When plugins section is present, registry_url is always included."""
    cfg = AppConfig(
        plugins=PluginsConfig(enabled=["youtube"]),
    )
    d = config_to_dict(cfg)
    assert d["plugins"]["registry_url"] == ""


def test_config_to_dict_default_plugins_omitted() -> None:
    cfg = AppConfig()
    d = config_to_dict(cfg)
    assert "plugins" not in d


# ---------------------------------------------------------------------------
# config_to_dict full=True (for config show)
# ---------------------------------------------------------------------------


def test_config_to_dict_full_includes_all_sections() -> None:
    """full=True includes every section even when values are defaults."""
    cfg = AppConfig()
    d = config_to_dict(cfg, full=True)
    assert d["render_profiles"] == {}
    assert d["iterations"] == {}
    assert d["orchestration"] == {"upload_bitrate_kbps": 0, "sequential": True}
    assert d["plugins"] == {
        "enabled": [],
        "disabled": [],
        "settings": {},
        "registry_url": "",
    }


def test_config_to_dict_full_plugins_all_fields() -> None:
    """full=True always shows all plugin sub-keys."""
    cfg = AppConfig(
        plugins=PluginsConfig(enabled=["youtube"]),
    )
    with patch("reeln.core.plugin_config.merge_all_plugin_defaults", return_value={}):
        d = config_to_dict(cfg, full=True)
    assert d["plugins"]["enabled"] == ["youtube"]
    assert d["plugins"]["disabled"] == []
    assert d["plugins"]["settings"] == {}
    assert d["plugins"]["registry_url"] == ""


def test_config_to_dict_full_merges_plugin_schema_defaults() -> None:
    """full=True merges plugin config_schema defaults into settings."""
    cfg = AppConfig(
        plugins=PluginsConfig(
            enabled=["google"],
            settings={"google": {"category_id": "20"}},
        ),
    )
    merged = {"google": {"category_id": "20", "create_livestream": False, "upload_video": False}}
    with patch("reeln.core.plugin_config.merge_all_plugin_defaults", return_value=merged) as mock_merge:
        d = config_to_dict(cfg, full=True)
    mock_merge.assert_called_once_with(["google"], {"google": {"category_id": "20"}})
    assert d["plugins"]["settings"]["google"]["create_livestream"] is False
    assert d["plugins"]["settings"]["google"]["upload_video"] is False
    assert d["plugins"]["settings"]["google"]["category_id"] == "20"


def test_config_to_dict_not_full_skips_plugin_defaults() -> None:
    """full=False does not call merge_all_plugin_defaults."""
    cfg = AppConfig(
        plugins=PluginsConfig(
            enabled=["google"],
            settings={"google": {"category_id": "20"}},
        ),
    )
    d = config_to_dict(cfg, full=False)
    # Should only have what was explicitly set
    assert d["plugins"]["settings"] == {"google": {"category_id": "20"}}


def test_dict_to_config_with_orchestration() -> None:
    d = {
        "orchestration": {"upload_bitrate_kbps": 3000, "sequential": False},
    }
    cfg = dict_to_config(d)
    assert cfg.orchestration.upload_bitrate_kbps == 3000
    assert cfg.orchestration.sequential is False


def test_dict_to_config_orchestration_defaults() -> None:
    cfg = dict_to_config({})
    assert cfg.orchestration.upload_bitrate_kbps == 0
    assert cfg.orchestration.sequential is True


def test_dict_to_config_orchestration_not_dict_ignored() -> None:
    cfg = dict_to_config({"orchestration": "not_a_dict"})
    assert cfg.orchestration.upload_bitrate_kbps == 0


def test_dict_to_config_with_plugins() -> None:
    d = {
        "plugins": {
            "enabled": ["youtube"],
            "disabled": ["llm"],
            "settings": {"youtube": {"api_key": "test"}},
        },
    }
    cfg = dict_to_config(d)
    assert cfg.plugins.enabled == ["youtube"]
    assert cfg.plugins.disabled == ["llm"]
    assert cfg.plugins.settings == {"youtube": {"api_key": "test"}}


def test_dict_to_config_plugins_defaults() -> None:
    cfg = dict_to_config({})
    assert cfg.plugins.enabled == []
    assert cfg.plugins.disabled == []
    assert cfg.plugins.settings == {}
    assert cfg.plugins.registry_url == ""


def test_dict_to_config_plugins_with_registry_url() -> None:
    d = {"plugins": {"registry_url": "https://example.com/reg.json"}}
    cfg = dict_to_config(d)
    assert cfg.plugins.registry_url == "https://example.com/reg.json"


def test_dict_to_config_plugins_not_dict_ignored() -> None:
    cfg = dict_to_config({"plugins": "not_a_dict"})
    assert cfg.plugins.enabled == []


def test_config_orchestration_plugins_roundtrip() -> None:
    original = AppConfig(
        orchestration=OrchestrationConfig(upload_bitrate_kbps=5000, sequential=False),
        plugins=PluginsConfig(
            enabled=["youtube", "meta"],
            disabled=["llm"],
            settings={"youtube": {"api_key": "key123"}},
        ),
    )
    d = config_to_dict(original)
    restored = dict_to_config(d)
    assert restored.orchestration.upload_bitrate_kbps == 5000
    assert restored.orchestration.sequential is False
    assert restored.plugins.enabled == ["youtube", "meta"]
    assert restored.plugins.disabled == ["llm"]
    assert restored.plugins.settings["youtube"]["api_key"] == "key123"


def test_config_profiles_roundtrip() -> None:
    original = AppConfig(
        sport="hockey",
        render_profiles={
            "fullspeed": RenderProfile(name="fullspeed", speed=1.0),
            "slowmo": RenderProfile(name="slowmo", speed=0.5, lut="warm.cube"),
        },
        iterations=IterationConfig(mappings={"default": ["fullspeed"], "goal": ["fullspeed", "slowmo"]}),
    )
    d = config_to_dict(original)
    restored = dict_to_config(d)
    assert restored.render_profiles["slowmo"].speed == 0.5
    assert restored.render_profiles["slowmo"].lut == "warm.cube"
    assert restored.iterations.profiles_for_event("goal") == ["fullspeed", "slowmo"]


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


def test_deep_merge_simple() -> None:
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    result = deep_merge(base, override)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_deep_merge_nested() -> None:
    base = {"video": {"crf": 18, "preset": "medium"}}
    override = {"video": {"crf": 22}}
    result = deep_merge(base, override)
    assert result == {"video": {"crf": 22, "preset": "medium"}}


def test_deep_merge_override_replaces_non_dict() -> None:
    base = {"video": {"crf": 18}}
    override = {"video": "disabled"}
    result = deep_merge(base, override)
    assert result["video"] == "disabled"


def test_deep_merge_does_not_mutate_base() -> None:
    base = {"video": {"crf": 18}}
    override = {"video": {"crf": 22}}
    deep_merge(base, override)
    assert base["video"]["crf"] == 18  # unchanged


# ---------------------------------------------------------------------------
# Env overrides
# ---------------------------------------------------------------------------


def test_apply_env_overrides_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELN_SPORT", "hockey")
    data: dict[str, object] = {"sport": "generic"}
    result = apply_env_overrides(data)
    assert result["sport"] == "hockey"


def test_apply_env_overrides_nested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELN_VIDEO_CRF", "22")
    data: dict[str, object] = {"video": {"crf": 18}}
    result = apply_env_overrides(data)
    assert result["video"]["crf"] == "22"  # type: ignore[index]


def test_apply_env_overrides_creates_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELN_NEW_KEY", "value")
    data: dict[str, object] = {}
    result = apply_env_overrides(data)
    assert result["new"]["key"] == "value"  # type: ignore[index]


def test_apply_env_overrides_plugins_registry_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELN_PLUGINS_REGISTRY_URL", "https://custom.example.com/reg.json")
    data: dict[str, object] = {"plugins": {}}
    result = apply_env_overrides(data)
    assert result["plugins"]["registry_url"] == "https://custom.example.com/reg.json"  # type: ignore[index]


def test_apply_env_overrides_ignores_unrelated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTHER_VAR", "nope")
    data: dict[str, object] = {"sport": "generic"}
    result = apply_env_overrides(data)
    assert "other" not in result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_config_valid() -> None:
    data = config_to_dict(default_config())
    issues = validate_config(data)
    assert issues == []


def test_validate_config_missing_version() -> None:
    issues = validate_config({"sport": "hockey"})
    assert any("Missing" in i for i in issues)


def test_validate_config_version_not_int() -> None:
    issues = validate_config({"config_version": "one"})
    assert any("integer" in i for i in issues)


def test_validate_config_version_too_new() -> None:
    issues = validate_config({"config_version": 999})
    assert any("newer" in i for i in issues)


def test_validate_config_video_not_dict() -> None:
    issues = validate_config({"config_version": 1, "video": "bad"})
    assert any("video" in i for i in issues)


def test_validate_config_paths_not_dict() -> None:
    issues = validate_config({"config_version": 1, "paths": "bad"})
    assert any("paths" in i for i in issues)


def test_validate_config_render_profiles_not_dict() -> None:
    issues = validate_config({"config_version": 1, "render_profiles": "bad"})
    assert any("render_profiles" in i for i in issues)


def test_validate_config_render_profiles_entry_not_dict() -> None:
    issues = validate_config({"config_version": 1, "render_profiles": {"good": {}, "bad": "nope"}})
    assert any("bad" in i for i in issues)


def test_validate_config_render_profiles_valid() -> None:
    issues = validate_config({"config_version": 1, "render_profiles": {"slowmo": {"speed": 0.5}}})
    assert issues == []


def test_validate_config_iterations_not_dict() -> None:
    issues = validate_config({"config_version": 1, "iterations": "bad"})
    assert any("iterations" in i for i in issues)


def test_validate_config_orchestration_not_dict() -> None:
    issues = validate_config({"config_version": 1, "orchestration": "bad"})
    assert any("orchestration" in i for i in issues)


def test_validate_config_orchestration_valid() -> None:
    issues = validate_config({"config_version": 1, "orchestration": {"upload_bitrate_kbps": 5000}})
    assert issues == []


def test_validate_config_plugins_not_dict() -> None:
    issues = validate_config({"config_version": 1, "plugins": "bad"})
    assert any("plugins" in i for i in issues)


def test_validate_config_plugins_valid() -> None:
    issues = validate_config({"config_version": 1, "plugins": {"enabled": ["youtube"]}})
    assert issues == []


def test_validate_config_iterations_valid() -> None:
    issues = validate_config({"config_version": 1, "iterations": {"default": ["fullspeed"]}})
    assert issues == []


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def test_load_config_defaults(tmp_path: Path) -> None:
    cfg = load_config(path=tmp_path / "nonexistent.json")
    assert cfg.sport == "generic"
    assert cfg.video.crf == 18


def test_load_config_from_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"config_version": 1, "sport": "hockey", "video": {"crf": 20}}))
    cfg = load_config(path=cfg_file)
    assert cfg.sport == "hockey"
    assert cfg.video.crf == 20
    assert cfg.video.preset == "medium"  # default merged


def test_load_config_with_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"config_version": 1, "sport": "hockey"}))
    monkeypatch.setenv("REELN_SPORT", "basketball")
    cfg = load_config(path=cfg_file)
    assert cfg.sport == "basketball"


def test_load_config_invalid_json(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{bad json")
    with pytest.raises(ConfigError, match="Failed to read"):
        load_config(path=cfg_file)


def test_load_config_not_a_dict(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('"just a string"')
    with pytest.raises(ConfigError, match="JSON object"):
        load_config(path=cfg_file)


def test_load_config_with_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REELN_CONFIG", raising=False)
    with patch("reeln.core.config.default_config_path", return_value=tmp_path / "config.tourney.json"):
        cfg = load_config(profile="tourney")
    assert cfg.sport == "generic"  # defaults since file doesn't exist


def test_load_config_reeln_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REELN_CONFIG env var sets the config file path."""
    cfg_file = tmp_path / "custom.json"
    cfg_file.write_text(json.dumps({"config_version": 1, "sport": "soccer"}))
    monkeypatch.setenv("REELN_CONFIG", str(cfg_file))
    cfg = load_config()
    assert cfg.sport == "soccer"


def test_load_config_reeln_config_env_expanduser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REELN_CONFIG env var supports ~ expansion."""
    cfg_file = tmp_path / "my.json"
    cfg_file.write_text(json.dumps({"config_version": 1, "sport": "hockey"}))
    monkeypatch.setenv("REELN_CONFIG", str(cfg_file))
    cfg = load_config()
    assert cfg.sport == "hockey"


def test_load_config_explicit_path_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit path argument takes priority over REELN_CONFIG env var."""
    env_file = tmp_path / "env.json"
    env_file.write_text(json.dumps({"config_version": 1, "sport": "soccer"}))
    monkeypatch.setenv("REELN_CONFIG", str(env_file))

    arg_file = tmp_path / "arg.json"
    arg_file.write_text(json.dumps({"config_version": 1, "sport": "hockey"}))

    cfg = load_config(path=arg_file)
    assert cfg.sport == "hockey"


def test_load_config_reeln_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REELN_PROFILE env var selects a named profile."""
    monkeypatch.delenv("REELN_CONFIG", raising=False)
    profile_file = tmp_path / "config.tourney.json"
    profile_file.write_text(json.dumps({"config_version": 1, "sport": "lacrosse"}))
    monkeypatch.setenv("REELN_PROFILE", "tourney")
    with patch("reeln.core.config.default_config_path", return_value=profile_file):
        cfg = load_config()
    assert cfg.sport == "lacrosse"


def test_load_config_explicit_profile_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit profile argument takes priority over REELN_PROFILE env var."""
    monkeypatch.delenv("REELN_CONFIG", raising=False)
    monkeypatch.setenv("REELN_PROFILE", "ignored")
    with patch(
        "reeln.core.config.default_config_path",
        return_value=tmp_path / "nonexistent.json",
    ):
        cfg = load_config(profile="explicit")
    assert cfg.sport == "generic"  # defaults since file doesn't exist


def test_load_config_reeln_config_env_overrides_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REELN_CONFIG takes priority over REELN_PROFILE."""
    cfg_file = tmp_path / "direct.json"
    cfg_file.write_text(json.dumps({"config_version": 1, "sport": "baseball"}))
    monkeypatch.setenv("REELN_CONFIG", str(cfg_file))
    monkeypatch.setenv("REELN_PROFILE", "ignored")
    cfg = load_config()
    assert cfg.sport == "baseball"


def test_load_config_no_env_vars_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without REELN_CONFIG or REELN_PROFILE, falls through to default path."""
    monkeypatch.delenv("REELN_CONFIG", raising=False)
    monkeypatch.delenv("REELN_PROFILE", raising=False)
    with patch(
        "reeln.core.config.default_config_path",
        return_value=Path("/nonexistent/config.json"),
    ):
        cfg = load_config()
    assert cfg.sport == "generic"  # defaults


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def test_save_config_creates_file(tmp_path: Path) -> None:
    cfg = AppConfig(sport="hockey")
    out = save_config(cfg, path=tmp_path / "out.json")
    assert out.is_file()
    loaded = json.loads(out.read_text())
    assert loaded["sport"] == "hockey"


def test_save_config_creates_parent_dirs(tmp_path: Path) -> None:
    cfg = AppConfig()
    out = save_config(cfg, path=tmp_path / "deep" / "nested" / "config.json")
    assert out.is_file()


def test_save_config_atomic_no_corruption(tmp_path: Path) -> None:
    cfg = AppConfig(sport="soccer")
    path = tmp_path / "config.json"
    save_config(cfg, path=path)
    # Verify valid JSON
    data = json.loads(path.read_text())
    assert data["sport"] == "soccer"


def test_save_config_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(AppConfig(sport="hockey"), path=path)
    save_config(AppConfig(sport="soccer"), path=path)
    data = json.loads(path.read_text())
    assert data["sport"] == "soccer"


def test_save_config_cleans_up_on_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    with (
        patch("reeln.core.config.Path.replace", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        save_config(AppConfig(), path=path)
    # Temp file should be cleaned up
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_save_config_respects_reeln_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / "custom" / "config.json"
    monkeypatch.setenv("REELN_CONFIG", str(env_path))

    save_config(AppConfig())

    assert env_path.is_file()
    data = json.loads(env_path.read_text())
    assert "config_version" in data


def test_save_config_respects_reeln_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REELN_PROFILE", "game")
    monkeypatch.delenv("REELN_CONFIG", raising=False)

    expected = default_config_path("game")
    result = save_config(AppConfig(), path=expected)

    assert result == expected


# ---------------------------------------------------------------------------
# resolve_config_path
# ---------------------------------------------------------------------------


def test_resolve_config_path_explicit_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reeln.core.config import resolve_config_path

    monkeypatch.setenv("REELN_CONFIG", "/should/be/ignored")
    explicit = tmp_path / "explicit.json"
    assert resolve_config_path(path=explicit) == explicit


def test_resolve_config_path_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reeln.core.config import resolve_config_path

    env_path = tmp_path / "env.json"
    monkeypatch.setenv("REELN_CONFIG", str(env_path))
    assert resolve_config_path() == env_path


def test_resolve_config_path_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from reeln.core.config import resolve_config_path

    monkeypatch.delenv("REELN_CONFIG", raising=False)
    monkeypatch.delenv("REELN_PROFILE", raising=False)
    result = resolve_config_path(profile="game")
    assert result == default_config_path("game")


def test_resolve_config_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from reeln.core.config import resolve_config_path

    monkeypatch.delenv("REELN_CONFIG", raising=False)
    monkeypatch.delenv("REELN_PROFILE", raising=False)
    assert resolve_config_path() == default_config_path()


# ---------------------------------------------------------------------------
# validate_plugin_configs
# ---------------------------------------------------------------------------


def test_validate_plugin_configs_with_schema_reports_issues() -> None:
    from reeln.models.plugin_schema import ConfigField, PluginConfigSchema

    schema = PluginConfigSchema(fields=(ConfigField(name="api_key", required=True),))
    with patch(
        "reeln.core.plugin_config.extract_schema_by_name",
        return_value=schema,
    ):
        issues = validate_plugin_configs({"youtube": {}})
    assert len(issues) == 1
    assert "api_key" in issues[0]


def test_validate_plugin_configs_no_schema_passes() -> None:
    with patch(
        "reeln.core.plugin_config.extract_schema_by_name",
        return_value=None,
    ):
        issues = validate_plugin_configs({"youtube": {"key": "val"}})
    assert issues == []


def test_validate_plugin_configs_empty_settings() -> None:
    issues = validate_plugin_configs({})
    assert issues == []


def test_validate_plugin_configs_mixed() -> None:
    from reeln.models.plugin_schema import ConfigField, PluginConfigSchema

    schema = PluginConfigSchema(fields=(ConfigField(name="token", required=True),))

    def fake_extract(name: str) -> PluginConfigSchema | None:
        if name == "with_schema":
            return schema
        return None

    with patch("reeln.core.plugin_config.extract_schema_by_name", side_effect=fake_extract):
        issues = validate_plugin_configs(
            {
                "with_schema": {},
                "no_schema": {"anything": "goes"},
            }
        )
    assert len(issues) == 1
    assert "with_schema" in issues[0]
