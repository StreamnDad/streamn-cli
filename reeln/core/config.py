"""Config loading, validation, merging, env overrides, and atomic writes."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from reeln.core.errors import ConfigError
from reeln.core.log import get_logger
from reeln.models.config import AppConfig, PathConfig, PluginsConfig, VideoConfig
from reeln.models.plugin import OrchestrationConfig
from reeln.models.profile import (
    IterationConfig,
    RenderProfile,
    dict_to_iteration_config,
    dict_to_render_profile,
    iteration_config_to_dict,
    render_profile_to_dict,
)

log: logging.Logger = get_logger(__name__)

CURRENT_CONFIG_VERSION: int = 1
_APP_NAME: str = "reeln"


# ---------------------------------------------------------------------------
# XDG-compliant paths
# ---------------------------------------------------------------------------


def config_dir() -> Path:
    """Return the platform-specific user config directory."""
    platform = sys.platform
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    if platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / _APP_NAME
        return Path.home() / "AppData" / "Roaming" / _APP_NAME  # pragma: no cover
    # Linux and others
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        return Path(xdg) / _APP_NAME
    return Path.home() / ".config" / _APP_NAME


def data_dir() -> Path:
    """Return the platform-specific user data directory."""
    platform = sys.platform
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME / "data"
    if platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / _APP_NAME / "data"
        return Path.home() / "AppData" / "Roaming" / _APP_NAME / "data"  # pragma: no cover
    # Linux and others
    xdg = os.environ.get("XDG_DATA_HOME", "")
    if xdg:
        return Path(xdg) / _APP_NAME
    return Path.home() / ".local" / "share" / _APP_NAME


def default_config_path(profile: str | None = None) -> Path:
    """Return the path to the config file, optionally for a named profile."""
    if profile:
        return config_dir() / f"config.{profile}.json"
    return config_dir() / "config.json"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def default_config() -> AppConfig:
    """Return an ``AppConfig`` with all default values.

    Includes a bundled ``player-overlay`` render profile and a ``goal``
    iteration mapping so goal events render with the overlay out of the box.
    """
    return AppConfig(
        render_profiles={
            "player-overlay": RenderProfile(
                name="player-overlay",
                subtitle_template="builtin:goal_overlay",
            ),
        },
        iterations=IterationConfig(
            mappings={
                "goal": ["player-overlay"],
            },
        ),
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def config_to_dict(config: AppConfig, *, full: bool = False) -> dict[str, Any]:
    """Serialize an ``AppConfig`` to a JSON-compatible dict.

    When *full* is ``True`` every section is included with its current
    value (used by ``config show``).  When ``False`` (the default),
    sections that equal their defaults are omitted so that
    ``save_config`` writes a minimal file.
    """
    d: dict[str, Any] = {
        "config_version": config.config_version,
        "sport": config.sport,
        "video": {
            "ffmpeg_path": config.video.ffmpeg_path,
            "codec": config.video.codec,
            "preset": config.video.preset,
            "crf": config.video.crf,
            "audio_codec": config.video.audio_codec,
            "audio_bitrate": config.video.audio_bitrate,
        },
        "paths": {
            "source_dir": str(config.paths.source_dir) if config.paths.source_dir else None,
            "source_glob": config.paths.source_glob,
            "output_dir": str(config.paths.output_dir) if config.paths.output_dir else None,
            "temp_dir": str(config.paths.temp_dir) if config.paths.temp_dir else None,
        },
    }

    if full or config.render_profiles:
        d["render_profiles"] = {
            name: render_profile_to_dict(profile) for name, profile in config.render_profiles.items()
        }
    if full or config.iterations.mappings:
        d["iterations"] = iteration_config_to_dict(config.iterations)
    if full or config.orchestration.upload_bitrate_kbps or not config.orchestration.sequential:
        d["orchestration"] = {
            "upload_bitrate_kbps": config.orchestration.upload_bitrate_kbps,
            "sequential": config.orchestration.sequential,
        }

    has_plugins = (
        config.plugins.enabled
        or config.plugins.disabled
        or config.plugins.settings
        or config.plugins.registry_url
    )
    if full or has_plugins:
        settings = dict(config.plugins.settings)
        if full and config.plugins.enabled:
            from reeln.core.plugin_config import merge_all_plugin_defaults

            settings = merge_all_plugin_defaults(config.plugins.enabled, settings)
        d["plugins"] = {
            "enabled": list(config.plugins.enabled),
            "disabled": list(config.plugins.disabled),
            "settings": settings,
            "registry_url": config.plugins.registry_url,
        }

    return d


def _dict_to_video_config(data: dict[str, Any]) -> VideoConfig:
    """Parse a ``video`` section dict into ``VideoConfig``."""
    return VideoConfig(
        ffmpeg_path=str(data.get("ffmpeg_path", "ffmpeg")),
        codec=str(data.get("codec", "libx264")),
        preset=str(data.get("preset", "medium")),
        crf=int(data.get("crf", 18)),
        audio_codec=str(data.get("audio_codec", "aac")),
        audio_bitrate=str(data.get("audio_bitrate", "128k")),
    )


def _dict_to_path_config(data: dict[str, Any]) -> PathConfig:
    """Parse a ``paths`` section dict into ``PathConfig``."""
    source_dir = data.get("source_dir")
    source_glob = data.get("source_glob")
    output_dir = data.get("output_dir")
    temp_dir = data.get("temp_dir")
    return PathConfig(
        source_dir=Path(source_dir).expanduser() if source_dir else None,
        source_glob=str(source_glob) if source_glob else "Replay_*.mkv",
        output_dir=Path(output_dir).expanduser() if output_dir else None,
        temp_dir=Path(temp_dir).expanduser() if temp_dir else None,
    )


def dict_to_config(data: dict[str, Any]) -> AppConfig:
    """Deserialize a dict into an ``AppConfig``."""
    # Render profiles
    raw_profiles = data.get("render_profiles", {})
    profiles = {}
    if isinstance(raw_profiles, dict):
        for name, pdata in raw_profiles.items():
            if isinstance(pdata, dict):
                profiles[str(name)] = dict_to_render_profile(str(name), pdata)

    # Iterations
    raw_iterations = data.get("iterations", {})
    iterations = dict_to_iteration_config(raw_iterations if isinstance(raw_iterations, dict) else {})

    # Orchestration
    raw_orch = data.get("orchestration", {})
    orchestration = OrchestrationConfig()
    if isinstance(raw_orch, dict):
        orchestration = OrchestrationConfig(
            upload_bitrate_kbps=int(raw_orch.get("upload_bitrate_kbps", 0)),
            sequential=bool(raw_orch.get("sequential", True)),
        )

    # Plugins
    raw_plugins = data.get("plugins", {})
    plugins_cfg = PluginsConfig()
    if isinstance(raw_plugins, dict):
        plugins_cfg = PluginsConfig(
            enabled=list(raw_plugins.get("enabled", [])),
            disabled=list(raw_plugins.get("disabled", [])),
            settings=dict(raw_plugins.get("settings", {})),
            registry_url=str(raw_plugins.get("registry_url", "")),
        )

    return AppConfig(
        config_version=int(data.get("config_version", CURRENT_CONFIG_VERSION)),
        sport=str(data.get("sport", "generic")),
        video=_dict_to_video_config(data.get("video", {})),
        paths=_dict_to_path_config(data.get("paths", {})),
        render_profiles=profiles,
        iterations=iterations,
        orchestration=orchestration,
        plugins=plugins_cfg,
    )


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Env var overrides
# ---------------------------------------------------------------------------

_ENV_PREFIX: str = "REELN_"


def apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply ``REELN_<SECTION>_<KEY>`` environment variable overrides.

    Supports one level of nesting: ``REELN_VIDEO_CRF=22`` sets
    ``data["video"]["crf"] = "22"``.  Top-level keys use a single
    segment: ``REELN_SPORT=basketball`` sets ``data["sport"]``.
    """
    result = dict(data)
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        suffix = key[len(_ENV_PREFIX) :].lower()
        parts = suffix.split("_", maxsplit=1)
        if len(parts) == 1:
            # Top-level: REELN_SPORT=basketball
            result[parts[0]] = value
        else:
            # Nested: REELN_VIDEO_CRF=22
            section, field = parts
            if section not in result or not isinstance(result[section], dict):
                result[section] = {}
            result[section] = dict(result[section])
            result[section][field] = value
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_config(data: dict[str, Any]) -> list[str]:
    """Validate a config dict. Returns a list of warning/error messages."""
    issues: list[str] = []
    version = data.get("config_version")
    if version is None:
        issues.append("Missing 'config_version' field")
    elif not isinstance(version, int):
        issues.append(f"'config_version' must be an integer, got {type(version).__name__}")
    elif version > CURRENT_CONFIG_VERSION:
        issues.append(
            f"Config version {version} is newer than supported ({CURRENT_CONFIG_VERSION}). Please upgrade reeln."
        )

    video = data.get("video")
    if video is not None and not isinstance(video, dict):
        issues.append("'video' section must be a dict")

    paths = data.get("paths")
    if paths is not None and not isinstance(paths, dict):
        issues.append("'paths' section must be a dict")

    render_profiles = data.get("render_profiles")
    if render_profiles is not None and not isinstance(render_profiles, dict):
        issues.append("'render_profiles' section must be a dict")
    elif isinstance(render_profiles, dict):
        for name, pdata in render_profiles.items():
            if not isinstance(pdata, dict):
                issues.append(f"render_profiles[{name!r}] must be a dict")

    iterations = data.get("iterations")
    if iterations is not None and not isinstance(iterations, dict):
        issues.append("'iterations' section must be a dict")

    orchestration = data.get("orchestration")
    if orchestration is not None and not isinstance(orchestration, dict):
        issues.append("'orchestration' section must be a dict")

    plugins = data.get("plugins")
    if plugins is not None and not isinstance(plugins, dict):
        issues.append("'plugins' section must be a dict")

    return issues


def validate_plugin_configs(settings: dict[str, dict[str, Any]]) -> list[str]:
    """Validate all plugin settings against declared schemas."""
    from reeln.core.plugin_config import extract_schema_by_name, validate_plugin_settings

    issues: list[str] = []
    for plugin_name, plugin_settings in settings.items():
        schema = extract_schema_by_name(plugin_name)
        if schema is None:
            continue
        issues.extend(validate_plugin_settings(plugin_name, plugin_settings, schema))
    return issues


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


def resolve_config_path(
    path: Path | None = None,
    profile: str | None = None,
) -> Path:
    """Resolve the config file path using the standard priority order.

    Priority:
    1. ``path`` argument (e.g. ``--config`` CLI flag)
    2. ``REELN_CONFIG`` environment variable
    3. ``profile`` argument (e.g. ``--profile`` CLI flag)
    4. ``REELN_PROFILE`` environment variable
    5. Default XDG path (``~/.config/reeln/config.json``)
    """
    if path is None:
        env_config = os.environ.get("REELN_CONFIG")
        if env_config:
            path = Path(env_config).expanduser()
    if path is None and profile is None:
        env_profile = os.environ.get("REELN_PROFILE")
        if env_profile:
            profile = env_profile
    return path or default_config_path(profile)


def load_config(
    path: Path | None = None,
    profile: str | None = None,
) -> AppConfig:
    """Load config from disk with env var overrides.

    Loading order: bundled defaults → user config file → env vars.

    The config file path can be set via (in priority order):
    1. ``path`` argument (e.g. ``--config`` CLI flag)
    2. ``REELN_CONFIG`` environment variable
    3. ``profile`` argument (e.g. ``--profile`` CLI flag)
    4. ``REELN_PROFILE`` environment variable
    5. Default XDG path (``~/.config/reeln/config.json``)
    """
    base = config_to_dict(default_config())

    file_path = resolve_config_path(path, profile)
    if file_path.is_file():
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"Failed to read config at {file_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(f"Config file must be a JSON object, got {type(raw).__name__}")

        merged = deep_merge(base, raw)
    else:
        merged = base
        log.debug("No config file at %s, using defaults", file_path)

    merged = apply_env_overrides(merged)

    issues = validate_config(merged)
    for issue in issues:
        log.warning("Config issue: %s", issue)

    return dict_to_config(merged)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    """Atomically write config to disk.

    Uses tempfile + ``Path.replace()`` to prevent corruption.
    Respects ``REELN_CONFIG`` / ``REELN_PROFILE`` env vars when no
    explicit *path* is given, matching the resolution order of
    :func:`load_config`.
    """
    file_path = resolve_config_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    data = config_to_dict(config)
    content = json.dumps(data, indent=2) + "\n"

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=file_path.parent, text=True)
    try:
        with open(tmp_fd, "w") as tmp:
            tmp.write(content)
            tmp.flush()
        Path(tmp_name).replace(file_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

    log.debug("Config saved to %s", file_path)
    return file_path
