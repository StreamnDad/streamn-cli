"""Plugin config schema extraction, default seeding, and validation."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

from reeln.core.log import get_logger
from reeln.models.plugin_schema import PluginConfigSchema, validate_value_type

log: logging.Logger = get_logger(__name__)

_ENTRY_POINT_GROUP: str = "reeln.plugins"


def extract_schema(plugin_cls: type) -> PluginConfigSchema | None:
    """Extract ``config_schema`` class attribute, return ``None`` if absent or wrong type."""
    raw = getattr(plugin_cls, "config_schema", None)
    if raw is None:
        return None
    if not isinstance(raw, PluginConfigSchema):
        return None
    return raw


def extract_schema_by_name(name: str) -> PluginConfigSchema | None:
    """Load a plugin class by entry point name (no instantiation) and extract its schema.

    Returns ``None`` if the plugin has no schema, is not found, or fails to load.
    """
    try:
        eps = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)
    except Exception:
        log.debug("Failed to read entry points", exc_info=True)
        return None

    matches = [ep for ep in eps if ep.name == name]
    if not matches:
        return None

    try:
        plugin_cls = matches[0].load()
    except Exception:
        log.debug("Failed to load plugin class %r", name, exc_info=True)
        return None

    return extract_schema(plugin_cls)


def seed_defaults(
    plugin_name: str,
    schema: PluginConfigSchema,
    existing_settings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge schema defaults into settings. Only adds missing keys.

    Returns a new dict — *existing_settings* is not mutated.
    """
    result = {k: dict(v) for k, v in existing_settings.items()}
    defaults = schema.defaults_dict()
    if not defaults:
        return result

    if plugin_name not in result:
        result[plugin_name] = {}

    for key, value in defaults.items():
        if key not in result[plugin_name]:
            result[plugin_name][key] = value

    return result


def merge_all_plugin_defaults(
    enabled: list[str],
    existing_settings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge schema defaults for all *enabled* plugins into *existing_settings*.

    Returns a new dict — *existing_settings* is not mutated.
    Plugins that are not installed or have no schema are silently skipped.
    """
    result = existing_settings
    for name in enabled:
        schema = extract_schema_by_name(name)
        if schema is not None:
            result = seed_defaults(name, schema, result)
    return result


def validate_plugin_settings(
    plugin_name: str,
    settings: dict[str, Any],
    schema: PluginConfigSchema,
) -> list[str]:
    """Validate *settings* against *schema*. Returns a list of issue strings.

    Checks for missing required fields and type mismatches.
    Extra fields not in the schema are ignored.
    """
    issues: list[str] = []

    for field_name in schema.required_fields():
        if field_name not in settings:
            issues.append(f"Plugin '{plugin_name}': missing required field '{field_name}'")

    for key, value in settings.items():
        field = schema.field_by_name(key)
        if field is None:
            continue
        if not validate_value_type(value, field):
            issues.append(
                f"Plugin '{plugin_name}': field '{key}' expected type '{field.field_type}', got {type(value).__name__}"
            )

    return issues
