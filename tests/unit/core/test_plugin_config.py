"""Tests for plugin config schema extraction, seeding, and validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from reeln.core.plugin_config import (
    extract_schema,
    extract_schema_by_name,
    merge_all_plugin_defaults,
    seed_defaults,
    validate_plugin_settings,
)
from reeln.models.plugin_schema import ConfigField, PluginConfigSchema

# ---------------------------------------------------------------------------
# extract_schema
# ---------------------------------------------------------------------------


class TestExtractSchema:
    def test_present(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="key"),))

        class Plugin:
            config_schema = schema

        assert extract_schema(Plugin) is schema

    def test_absent(self) -> None:
        class Plugin:
            pass

        assert extract_schema(Plugin) is None

    def test_wrong_type(self) -> None:
        class Plugin:
            config_schema = {"not": "a schema"}  # noqa: RUF012

        assert extract_schema(Plugin) is None

    def test_not_plugin_config_schema_instance(self) -> None:
        class Plugin:
            config_schema = "a string"

        assert extract_schema(Plugin) is None


# ---------------------------------------------------------------------------
# extract_schema_by_name
# ---------------------------------------------------------------------------


class TestExtractSchemaByName:
    def test_found_with_schema(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="key"),))

        class FakePlugin:
            config_schema = schema

        ep = MagicMock()
        ep.name = "youtube"
        ep.load.return_value = FakePlugin

        with patch(
            "reeln.core.plugin_config.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            result = extract_schema_by_name("youtube")

        assert result is schema

    def test_found_no_schema(self) -> None:
        class FakePlugin:
            pass

        ep = MagicMock()
        ep.name = "youtube"
        ep.load.return_value = FakePlugin

        with patch(
            "reeln.core.plugin_config.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            result = extract_schema_by_name("youtube")

        assert result is None

    def test_not_found(self) -> None:
        with patch(
            "reeln.core.plugin_config.importlib.metadata.entry_points",
            return_value=[],
        ):
            result = extract_schema_by_name("nonexistent")

        assert result is None

    def test_load_failure(self) -> None:
        ep = MagicMock()
        ep.name = "broken"
        ep.load.side_effect = ImportError("bad module")

        with patch(
            "reeln.core.plugin_config.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            result = extract_schema_by_name("broken")

        assert result is None

    def test_entry_points_failure(self) -> None:
        with patch(
            "reeln.core.plugin_config.importlib.metadata.entry_points",
            side_effect=Exception("cannot read"),
        ):
            result = extract_schema_by_name("anything")

        assert result is None


# ---------------------------------------------------------------------------
# seed_defaults
# ---------------------------------------------------------------------------


class TestSeedDefaults:
    def _schema(self) -> PluginConfigSchema:
        return PluginConfigSchema(
            fields=(
                ConfigField(name="host", default="localhost"),
                ConfigField(name="port", field_type="int", default=8080),
                ConfigField(name="token"),  # No default
            )
        )

    def test_new_plugin(self) -> None:
        result = seed_defaults("myplugin", self._schema(), {})
        assert result == {"myplugin": {"host": "localhost", "port": 8080}}

    def test_merge_existing(self) -> None:
        existing = {"myplugin": {"extra": "val"}}
        result = seed_defaults("myplugin", self._schema(), existing)
        assert result["myplugin"]["host"] == "localhost"
        assert result["myplugin"]["port"] == 8080
        assert result["myplugin"]["extra"] == "val"

    def test_no_overwrite(self) -> None:
        existing = {"myplugin": {"host": "custom.example.com", "port": 9090}}
        result = seed_defaults("myplugin", self._schema(), existing)
        assert result["myplugin"]["host"] == "custom.example.com"
        assert result["myplugin"]["port"] == 9090

    def test_empty_schema(self) -> None:
        result = seed_defaults("myplugin", PluginConfigSchema(), {})
        assert result == {}

    def test_no_defaults_in_schema(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="token", required=True),))
        result = seed_defaults("myplugin", schema, {})
        assert result == {}

    def test_does_not_mutate_input(self) -> None:
        existing = {"myplugin": {"extra": "val"}}
        original_inner = dict(existing["myplugin"])
        seed_defaults("myplugin", self._schema(), existing)
        assert existing["myplugin"] == original_inner


# ---------------------------------------------------------------------------
# validate_plugin_settings
# ---------------------------------------------------------------------------


class TestValidatePluginSettings:
    def test_valid(self) -> None:
        schema = PluginConfigSchema(
            fields=(
                ConfigField(name="host", field_type="str"),
                ConfigField(name="port", field_type="int"),
            )
        )
        issues = validate_plugin_settings("p", {"host": "localhost", "port": 80}, schema)
        assert issues == []

    def test_missing_required(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="api_key", required=True),))
        issues = validate_plugin_settings("p", {}, schema)
        assert len(issues) == 1
        assert "missing required" in issues[0]
        assert "api_key" in issues[0]

    def test_wrong_type(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="port", field_type="int"),))
        issues = validate_plugin_settings("p", {"port": "not_an_int"}, schema)
        assert len(issues) == 1
        assert "expected type" in issues[0]

    def test_extra_fields_ignored(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="host", field_type="str"),))
        issues = validate_plugin_settings("p", {"host": "ok", "extra": 99}, schema)
        assert issues == []

    def test_empty_settings_with_required(self) -> None:
        schema = PluginConfigSchema(
            fields=(
                ConfigField(name="a", required=True),
                ConfigField(name="b", required=True),
            )
        )
        issues = validate_plugin_settings("p", {}, schema)
        assert len(issues) == 2

    def test_empty_schema(self) -> None:
        issues = validate_plugin_settings("p", {"anything": "goes"}, PluginConfigSchema())
        assert issues == []

    def test_multiple_issues(self) -> None:
        schema = PluginConfigSchema(
            fields=(
                ConfigField(name="key", required=True),
                ConfigField(name="port", field_type="int"),
            )
        )
        issues = validate_plugin_settings("p", {"port": "bad"}, schema)
        assert len(issues) == 2
        assert any("missing required" in i for i in issues)
        assert any("expected type" in i for i in issues)

    def test_required_field_present(self) -> None:
        schema = PluginConfigSchema(fields=(ConfigField(name="api_key", field_type="str", required=True),))
        issues = validate_plugin_settings("p", {"api_key": "abc"}, schema)
        assert issues == []


# ---------------------------------------------------------------------------
# merge_all_plugin_defaults
# ---------------------------------------------------------------------------


class TestMergeAllPluginDefaults:
    def _schema(self) -> PluginConfigSchema:
        return PluginConfigSchema(
            fields=(
                ConfigField(name="enabled", field_type="bool", default=False),
                ConfigField(name="timeout", field_type="int", default=30),
            )
        )

    def test_merges_defaults_for_installed_plugin(self) -> None:
        with patch(
            "reeln.core.plugin_config.extract_schema_by_name",
            return_value=self._schema(),
        ):
            result = merge_all_plugin_defaults(["myplugin"], {})
        assert result == {"myplugin": {"enabled": False, "timeout": 30}}

    def test_preserves_existing_settings(self) -> None:
        existing = {"myplugin": {"timeout": 60}}
        with patch(
            "reeln.core.plugin_config.extract_schema_by_name",
            return_value=self._schema(),
        ):
            result = merge_all_plugin_defaults(["myplugin"], existing)
        assert result["myplugin"]["timeout"] == 60
        assert result["myplugin"]["enabled"] is False

    def test_skips_plugins_without_schema(self) -> None:
        with patch(
            "reeln.core.plugin_config.extract_schema_by_name",
            return_value=None,
        ):
            result = merge_all_plugin_defaults(["noschemaplugin"], {"other": {"k": "v"}})
        assert result == {"other": {"k": "v"}}

    def test_multiple_plugins(self) -> None:
        schema_a = PluginConfigSchema(
            fields=(ConfigField(name="flag_a", field_type="bool", default=True),)
        )
        schema_b = PluginConfigSchema(
            fields=(ConfigField(name="flag_b", field_type="bool", default=False),)
        )

        def _mock_schema(name: str) -> PluginConfigSchema | None:
            return {"a": schema_a, "b": schema_b}.get(name)

        with patch(
            "reeln.core.plugin_config.extract_schema_by_name",
            side_effect=_mock_schema,
        ):
            result = merge_all_plugin_defaults(["a", "b"], {})
        assert result["a"]["flag_a"] is True
        assert result["b"]["flag_b"] is False

    def test_does_not_mutate_input(self) -> None:
        existing = {"myplugin": {"timeout": 60}}
        original = {"myplugin": {"timeout": 60}}
        with patch(
            "reeln.core.plugin_config.extract_schema_by_name",
            return_value=self._schema(),
        ):
            merge_all_plugin_defaults(["myplugin"], existing)
        assert existing == original

    def test_empty_enabled_list(self) -> None:
        result = merge_all_plugin_defaults([], {"other": {"k": "v"}})
        assert result == {"other": {"k": "v"}}
