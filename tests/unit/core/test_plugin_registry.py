"""Tests for the remote plugin registry module."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reeln.core.errors import RegistryError
from reeln.core.plugin_registry import (
    PipResult,
    _cache_dir,
    _cache_meta_path,
    _cache_path,
    _fetch_remote,
    _is_cache_fresh,
    _parse_registry_json,
    _read_cache,
    _resolve_entry,
    _resolve_install_target,
    _resolve_package,
    _run_pip,
    _write_cache,
    build_plugin_status,
    detect_installer,
    fetch_registry,
    get_installed_version,
    get_pypi_version,
    install_plugin,
    update_all_plugins,
    update_plugin,
)
from reeln.models.plugin import PluginInfo, RegistryEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_ENTRIES = [
    RegistryEntry(
        name="youtube",
        package="reeln-youtube",
        description="YouTube uploader",
        capabilities=["uploader"],
    ),
    RegistryEntry(
        name="llm",
        package="reeln-llm",
        description="LLM enricher",
        capabilities=["enricher", "generator"],
    ),
]

_SAMPLE_REGISTRY_JSON = {
    "registry_version": 1,
    "plugins": [
        {
            "name": "youtube",
            "package": "reeln-youtube",
            "description": "YouTube uploader",
            "capabilities": ["uploader"],
        },
        {
            "name": "llm",
            "package": "reeln-llm",
            "description": "LLM enricher",
            "capabilities": ["enricher", "generator"],
        },
    ],
}


@pytest.fixture()
def fake_cache_dir(tmp_path: Path) -> Path:
    """Redirect cache dir to a temporary directory."""
    cache = tmp_path / "registry"
    cache.mkdir()
    return cache


# ---------------------------------------------------------------------------
# Cache subsystem
# ---------------------------------------------------------------------------


def test_cache_dir_uses_data_dir(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        assert _cache_dir() == tmp_path / "registry"


def test_cache_path(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        assert _cache_path() == tmp_path / "registry" / "plugins.json"


def test_cache_meta_path(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        assert _cache_meta_path() == tmp_path / "registry" / "cache_meta.json"


def test_write_cache_creates_files(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        _write_cache(_SAMPLE_ENTRIES)
        assert _cache_path().is_file()
        assert _cache_meta_path().is_file()

        data = json.loads(_cache_path().read_text())
        assert data["registry_version"] == 1
        assert len(data["plugins"]) == 2

        meta = json.loads(_cache_meta_path().read_text())
        assert "fetched_at" in meta


def test_write_cache_atomic_cleanup(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        cache_d = tmp_path / "registry"
        cache_d.mkdir(parents=True, exist_ok=True)

        with (
            patch("reeln.core.plugin_registry.Path.replace", side_effect=OSError("disk")),
            pytest.raises(OSError, match="disk"),
        ):
            _write_cache([])

        tmp_files = list(cache_d.glob("*.tmp"))
        assert tmp_files == []


def test_read_cache_valid(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        _write_cache(_SAMPLE_ENTRIES)
        result = _read_cache()
        assert result is not None
        assert len(result) == 2
        assert result[0].name == "youtube"


def test_read_cache_missing(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        assert _read_cache() is None


def test_read_cache_corrupt(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        cache_d = tmp_path / "registry"
        cache_d.mkdir(parents=True, exist_ok=True)
        (cache_d / "plugins.json").write_text("{corrupt json")
        assert _read_cache() is None


def test_is_cache_fresh_no_meta(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        assert _is_cache_fresh() is False


def test_is_cache_fresh_valid(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        _write_cache(_SAMPLE_ENTRIES)
        assert _is_cache_fresh() is True


def test_is_cache_stale(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        _write_cache(_SAMPLE_ENTRIES)
        # Backdate the meta
        meta = json.loads(_cache_meta_path().read_text())
        meta["fetched_at"] = time.time() - 7200  # 2 hours ago
        _cache_meta_path().write_text(json.dumps(meta))
        assert _is_cache_fresh() is False


def test_is_cache_fresh_corrupt_meta(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        cache_d = tmp_path / "registry"
        cache_d.mkdir(parents=True, exist_ok=True)
        (cache_d / "cache_meta.json").write_text("{bad")
        assert _is_cache_fresh() is False


# ---------------------------------------------------------------------------
# Fetch subsystem
# ---------------------------------------------------------------------------


def test_parse_registry_json_valid() -> None:
    result = _parse_registry_json(_SAMPLE_REGISTRY_JSON)
    assert len(result) == 2
    assert result[0].name == "youtube"
    assert result[1].package == "reeln-llm"


def test_parse_registry_json_missing_plugins_key() -> None:
    with pytest.raises(KeyError, match="plugins"):
        _parse_registry_json({"registry_version": 1})


def test_parse_registry_json_plugins_not_list() -> None:
    with pytest.raises(KeyError, match="plugins"):
        _parse_registry_json({"plugins": "not_a_list"})


def test_parse_registry_json_skips_non_dict_entries() -> None:
    data = {"plugins": [{"name": "good"}, "bad_entry", 42]}
    result = _parse_registry_json(data)
    assert len(result) == 1
    assert result[0].name == "good"


def test_fetch_remote_success() -> None:
    body = json.dumps(_SAMPLE_REGISTRY_JSON).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_remote("https://example.com/reg.json")
    assert len(result) == 2


def test_fetch_remote_network_error() -> None:
    import urllib.error

    with (
        patch(
            "reeln.core.plugin_registry.urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ),
        pytest.raises(RegistryError, match="Failed to fetch"),
    ):
        _fetch_remote("https://example.com/reg.json")


def test_fetch_remote_invalid_json() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not json"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with (
        patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp),
        pytest.raises(RegistryError, match="Failed to fetch"),
    ):
        _fetch_remote("https://example.com/reg.json")


def test_fetch_remote_invalid_format() -> None:
    body = json.dumps({"no_plugins_key": True}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with (
        patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp),
        pytest.raises(RegistryError, match="Invalid registry format"),
    ):
        _fetch_remote("https://example.com/reg.json")


def test_fetch_registry_uses_cache(tmp_path: Path) -> None:
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        _write_cache(_SAMPLE_ENTRIES)
        result = fetch_registry()
        assert len(result) == 2


def test_fetch_registry_force_refresh(tmp_path: Path) -> None:
    body = json.dumps(_SAMPLE_REGISTRY_JSON).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with (
        patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path),
        patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp),
    ):
        _write_cache(_SAMPLE_ENTRIES)
        result = fetch_registry(force_refresh=True)
        assert len(result) == 2


def test_fetch_registry_custom_url(tmp_path: Path) -> None:
    body = json.dumps(_SAMPLE_REGISTRY_JSON).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with (
        patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path),
        patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp) as mock_open,
    ):
        result = fetch_registry("https://custom.example.com/reg.json", force_refresh=True)
        assert len(result) == 2
        # Verify the custom URL was used
        call_args = mock_open.call_args
        req = call_args[0][0]
        assert req.full_url == "https://custom.example.com/reg.json"


def test_fetch_registry_falls_back_to_stale_cache(tmp_path: Path) -> None:
    import urllib.error

    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        _write_cache(_SAMPLE_ENTRIES)
        # Backdate cache to make it stale
        meta = json.loads(_cache_meta_path().read_text())
        meta["fetched_at"] = time.time() - 7200
        _cache_meta_path().write_text(json.dumps(meta))

        with patch(
            "reeln.core.plugin_registry.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            result = fetch_registry()
            assert len(result) == 2


def test_fetch_registry_raises_when_no_cache(tmp_path: Path) -> None:
    import urllib.error

    with (
        patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path),
        patch(
            "reeln.core.plugin_registry.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ),
        pytest.raises(RegistryError, match="Failed to fetch"),
    ):
        fetch_registry()


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------


def test_get_installed_version_found() -> None:
    with patch("importlib.metadata.version", return_value="1.2.3"):
        assert get_installed_version("some-package") == "1.2.3"


def test_get_installed_version_not_found() -> None:
    with patch("importlib.metadata.version", side_effect=Exception("not found")):
        assert get_installed_version("missing-package") == ""


def test_get_pypi_version_success() -> None:
    body = json.dumps({"info": {"version": "2.0.0"}}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp):
        assert get_pypi_version("reeln-youtube") == "2.0.0"


def test_get_pypi_version_timeout() -> None:
    import urllib.error

    with patch(
        "reeln.core.plugin_registry.urllib.request.urlopen",
        side_effect=urllib.error.URLError("timeout"),
    ):
        assert get_pypi_version("reeln-youtube") == ""


def test_get_pypi_version_not_found() -> None:
    import urllib.error

    with patch(
        "reeln.core.plugin_registry.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "url",
            404,
            "Not Found",
            {},
            None,  # type: ignore[arg-type]
        ),
    ):
        assert get_pypi_version("nonexistent") == ""


def test_get_pypi_version_bad_json() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not json"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("reeln.core.plugin_registry.urllib.request.urlopen", return_value=mock_resp):
        assert get_pypi_version("reeln-youtube") == ""


# ---------------------------------------------------------------------------
# Status building
# ---------------------------------------------------------------------------


def test_build_plugin_status_installed_and_registry() -> None:
    entries = [
        RegistryEntry(name="youtube", package="reeln-youtube", description="YT", capabilities=["uploader"]),
    ]
    installed = [PluginInfo(name="youtube", entry_point="yt:P")]

    with (
        patch("reeln.core.plugin_registry.get_installed_version", return_value="1.0.0"),
        patch("reeln.core.plugin_registry.get_pypi_version", return_value="1.1.0"),
    ):
        result = build_plugin_status(entries, installed, [], [])

    assert len(result) == 1
    assert result[0].installed is True
    assert result[0].installed_version == "1.0.0"
    assert result[0].available_version == "1.1.0"
    assert result[0].update_available is True
    assert result[0].enabled is True


def test_build_plugin_status_installed_only() -> None:
    installed = [PluginInfo(name="custom", entry_point="c:P", capabilities=["notifier"])]

    with (
        patch("reeln.core.plugin_registry.get_installed_version", return_value=""),
        patch("reeln.core.plugin_registry.get_pypi_version", return_value=""),
    ):
        result = build_plugin_status([], installed, [], [])

    assert len(result) == 1
    assert result[0].installed is True
    assert result[0].capabilities == ["notifier"]


def test_build_plugin_status_registry_only() -> None:
    entries = [
        RegistryEntry(name="meta", package="reeln-meta", description="Meta", capabilities=["uploader"]),
    ]

    with patch("reeln.core.plugin_registry.get_pypi_version", return_value="1.0.0"):
        result = build_plugin_status(entries, [], [], [])

    assert len(result) == 1
    assert result[0].installed is False
    assert result[0].enabled is False


def test_build_plugin_status_enabled_disabled() -> None:
    entries = [
        RegistryEntry(name="youtube", package="reeln-youtube"),
        RegistryEntry(name="llm", package="reeln-llm"),
    ]
    installed = [
        PluginInfo(name="youtube", entry_point="yt:P"),
        PluginInfo(name="llm", entry_point="llm:P"),
    ]

    with (
        patch("reeln.core.plugin_registry.get_installed_version", return_value="1.0.0"),
        patch("reeln.core.plugin_registry.get_pypi_version", return_value="1.0.0"),
    ):
        result = build_plugin_status(entries, installed, ["youtube"], ["llm"])

    yt = next(s for s in result if s.name == "youtube")
    llm = next(s for s in result if s.name == "llm")
    assert yt.enabled is True
    assert llm.enabled is False


def test_build_plugin_status_no_update_when_same_version() -> None:
    entries = [RegistryEntry(name="youtube", package="reeln-youtube")]
    installed = [PluginInfo(name="youtube", entry_point="yt:P")]

    with (
        patch("reeln.core.plugin_registry.get_installed_version", return_value="1.0.0"),
        patch("reeln.core.plugin_registry.get_pypi_version", return_value="1.0.0"),
    ):
        result = build_plugin_status(entries, installed, [], [])

    assert result[0].update_available is False


# ---------------------------------------------------------------------------
# Installer detection
# ---------------------------------------------------------------------------


def test_detect_installer_uv_found() -> None:
    with patch("reeln.core.plugin_registry.shutil.which", return_value="/usr/bin/uv"):
        result = detect_installer()
    assert result == ["uv", "pip", "install"]


def test_detect_installer_uv_not_found() -> None:
    with patch("reeln.core.plugin_registry.shutil.which", return_value=None):
        result = detect_installer()
    assert result[0].endswith("python") or "python" in result[0]
    assert result[1:] == ["-m", "pip", "install"]


def test_detect_installer_uses_sys_executable() -> None:
    with (
        patch("reeln.core.plugin_registry.shutil.which", return_value=None),
        patch("reeln.core.plugin_registry.sys.executable", "/usr/bin/python3.11"),
    ):
        result = detect_installer()
    assert result[0] == "/usr/bin/python3.11"


# ---------------------------------------------------------------------------
# Pip runner
# ---------------------------------------------------------------------------


def test_run_pip_success() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "Successfully installed pkg"
    proc.stderr = ""

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc):
        result = _run_pip(["reeln-youtube"])
    assert result.success is True
    assert "Successfully installed" in result.output


def test_run_pip_failure() -> None:
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "ERROR: No matching distribution"

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc):
        result = _run_pip(["nonexistent-pkg"])
    assert result.success is False
    assert "No matching distribution" in result.error


def test_run_pip_dry_run() -> None:
    result = _run_pip(["reeln-youtube"], dry_run=True)
    assert result.success is True
    assert "Would run:" in result.output


def test_run_pip_permission_retry() -> None:
    fail_proc = MagicMock()
    fail_proc.returncode = 1
    fail_proc.stderr = "ERROR: Permission denied"

    success_proc = MagicMock()
    success_proc.returncode = 0
    success_proc.stdout = "Installed with --user"
    success_proc.stderr = ""

    with patch(
        "reeln.core.plugin_registry.subprocess.run",
        side_effect=[fail_proc, success_proc],
    ):
        result = _run_pip(["reeln-youtube"])
    assert result.success is True


def test_run_pip_permission_retry_also_fails() -> None:
    fail_proc = MagicMock()
    fail_proc.returncode = 1
    fail_proc.stderr = "ERROR: Permission denied"

    fail_proc2 = MagicMock()
    fail_proc2.returncode = 1
    fail_proc2.stderr = "Still denied"

    with patch(
        "reeln.core.plugin_registry.subprocess.run",
        side_effect=[fail_proc, fail_proc2],
    ):
        result = _run_pip(["reeln-youtube"])
    assert result.success is False


def test_run_pip_timeout() -> None:
    import subprocess

    with patch(
        "reeln.core.plugin_registry.subprocess.run",
        side_effect=subprocess.TimeoutExpired("cmd", 120),
    ):
        result = _run_pip(["reeln-youtube"])
    assert result.success is False
    assert "timed out" in result.error


def test_run_pip_with_installer_uv() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "ok"
    proc.stderr = ""

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc) as mock_run:
        _run_pip(["reeln-youtube"], installer="uv")
    cmd = mock_run.call_args[0][0]
    assert cmd[:3] == ["uv", "pip", "install"]


def test_run_pip_with_installer_pip() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "ok"
    proc.stderr = ""

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc) as mock_run:
        _run_pip(["reeln-youtube"], installer="pip")
    cmd = mock_run.call_args[0][0]
    assert cmd[1:] == ["-m", "pip", "install", "reeln-youtube"]


# ---------------------------------------------------------------------------
# Resolve entry / package / install target
# ---------------------------------------------------------------------------


def test_resolve_entry_found() -> None:
    entry = _resolve_entry("youtube", _SAMPLE_ENTRIES)
    assert entry.name == "youtube"
    assert entry.package == "reeln-youtube"


def test_resolve_entry_not_found() -> None:
    with pytest.raises(RegistryError, match="not found in the registry"):
        _resolve_entry("nonexistent", _SAMPLE_ENTRIES)


def test_resolve_package_found() -> None:
    package = _resolve_package("youtube", _SAMPLE_ENTRIES)
    assert package == "reeln-youtube"


def test_resolve_package_not_found() -> None:
    with pytest.raises(RegistryError, match="not found in the registry"):
        _resolve_package("nonexistent", _SAMPLE_ENTRIES)


def test_resolve_install_target_github() -> None:
    entry = RegistryEntry(
        name="scoreboard",
        package="reeln-plugin-scoreboard",
        homepage="https://github.com/StreamnDad/reeln-plugin-scoreboard",
    )
    assert _resolve_install_target(entry) == "git+https://github.com/StreamnDad/reeln-plugin-scoreboard"


def test_resolve_install_target_gitlab() -> None:
    entry = RegistryEntry(
        name="test",
        package="reeln-test",
        homepage="https://gitlab.com/user/reeln-test",
    )
    assert _resolve_install_target(entry) == "git+https://gitlab.com/user/reeln-test"


def test_resolve_install_target_no_homepage_falls_back_to_package() -> None:
    entry = RegistryEntry(name="youtube", package="reeln-youtube")
    assert _resolve_install_target(entry) == "reeln-youtube"


def test_resolve_install_target_non_git_homepage_falls_back_to_package() -> None:
    entry = RegistryEntry(
        name="custom",
        package="reeln-custom",
        homepage="https://example.com/custom-plugin",
    )
    assert _resolve_install_target(entry) == "reeln-custom"


# ---------------------------------------------------------------------------
# Install / update
# ---------------------------------------------------------------------------


def test_install_plugin_success() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "Installed"
    proc.stderr = ""

    with (
        patch("reeln.core.plugin_registry.subprocess.run", return_value=proc),
        patch("reeln.core.plugin_registry.get_installed_version", return_value="1.0.0"),
    ):
        result = install_plugin("youtube", _SAMPLE_ENTRIES)
    assert result.success is True


def test_install_plugin_not_in_registry() -> None:
    with pytest.raises(RegistryError, match="not found"):
        install_plugin("nonexistent", _SAMPLE_ENTRIES)


def test_install_plugin_dry_run() -> None:
    result = install_plugin("youtube", _SAMPLE_ENTRIES, dry_run=True)
    assert result.success is True
    assert "Would run:" in result.output


def test_install_plugin_pip_failure() -> None:
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "ERROR: failed"

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc):
        result = install_plugin("youtube", _SAMPLE_ENTRIES)
    assert result.success is False


def test_install_plugin_verification_fails() -> None:
    """pip returns 0 but package not actually installed (uv no-op bug)."""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "Audited"
    proc.stderr = ""

    with (
        patch("reeln.core.plugin_registry.subprocess.run", return_value=proc),
        patch("reeln.core.plugin_registry.get_installed_version", return_value=""),
    ):
        result = install_plugin("youtube", _SAMPLE_ENTRIES)
    assert result.success is False
    assert "not found after install" in result.error


def test_install_plugin_uses_git_homepage() -> None:
    """Plugins with GitHub homepage install via git+URL."""
    entries = [
        RegistryEntry(
            name="scoreboard",
            package="reeln-plugin-streamn-scoreboard",
            homepage="https://github.com/StreamnDad/reeln-plugin-streamn-scoreboard",
        ),
    ]
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "Installed"
    proc.stderr = ""

    with (
        patch("reeln.core.plugin_registry.subprocess.run", return_value=proc) as mock_run,
        patch("reeln.core.plugin_registry.get_installed_version", return_value="0.1.0"),
    ):
        result = install_plugin("scoreboard", entries)
    assert result.success is True
    # Verify git+URL was passed to pip
    cmd = mock_run.call_args[0][0]
    assert any("git+https://github.com/" in arg for arg in cmd)


def test_update_plugin_success() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "Updated"
    proc.stderr = ""

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc):
        result = update_plugin("youtube", _SAMPLE_ENTRIES)
    assert result.success is True
    assert result.action == "update"
    assert result.package == "reeln-youtube"


def test_update_plugin_not_in_registry() -> None:
    with pytest.raises(RegistryError, match="not found"):
        update_plugin("nonexistent", _SAMPLE_ENTRIES)


def test_update_all_plugins() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "Updated"
    proc.stderr = ""

    installed = [
        PluginInfo(name="youtube", entry_point="yt:P"),
        PluginInfo(name="llm", entry_point="llm:P"),
    ]

    with patch("reeln.core.plugin_registry.subprocess.run", return_value=proc):
        results = update_all_plugins(_SAMPLE_ENTRIES, installed)
    assert len(results) == 2
    assert all(r.success for r in results)


def test_update_all_plugins_nothing_in_registry() -> None:
    installed = [PluginInfo(name="custom", entry_point="c:P")]
    results = update_all_plugins(_SAMPLE_ENTRIES, installed)
    assert results == []


def test_update_all_plugins_dry_run() -> None:
    installed = [PluginInfo(name="youtube", entry_point="yt:P")]
    results = update_all_plugins(_SAMPLE_ENTRIES, installed, dry_run=True)
    assert len(results) == 1
    assert results[0].success is True
    assert "Would run:" in results[0].output


# ---------------------------------------------------------------------------
# PipResult
# ---------------------------------------------------------------------------


def test_run_pip_generic_exception() -> None:
    with patch(
        "reeln.core.plugin_registry.subprocess.run",
        side_effect=RuntimeError("unexpected"),
    ):
        result = _run_pip(["reeln-youtube"])
    assert result.success is False
    assert "unexpected" in result.error


def test_write_cache_meta_cleanup_on_error(tmp_path: Path) -> None:
    """The except branch for meta file write is covered by simulating failure
    on the second replace (meta file)."""
    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        cache_d = tmp_path / "registry"
        cache_d.mkdir(parents=True, exist_ok=True)

        call_count = 0
        original_replace = Path.replace

        def failing_replace(self: Path, target: Path) -> Path:
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # second replace is the meta file
                raise OSError("meta write failed")
            return original_replace(self, target)

        with (
            patch.object(Path, "replace", failing_replace),
            pytest.raises(OSError, match="meta write failed"),
        ):
            _write_cache([])

        # Temp files should be cleaned up
        tmp_files = list(cache_d.glob("*.tmp"))
        assert tmp_files == []


def test_fetch_registry_cache_fresh_but_read_fails(tmp_path: Path) -> None:
    """When cache reports fresh but the data file is corrupt, fetch from remote."""
    body = json.dumps(_SAMPLE_REGISTRY_JSON).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("reeln.core.plugin_registry.data_dir", return_value=tmp_path):
        # Write valid cache first to get meta file
        _write_cache(_SAMPLE_ENTRIES)
        # Corrupt the data file
        _cache_path().write_text("{corrupt")

        with patch(
            "reeln.core.plugin_registry.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = fetch_registry()
        assert len(result) == 2


def test_build_plugin_status_enabled_filter_registry_only() -> None:
    """Registry-only plugin with enabled filter should be disabled."""
    entries = [RegistryEntry(name="meta", package="reeln-meta")]

    with patch("reeln.core.plugin_registry.get_pypi_version", return_value="1.0.0"):
        result = build_plugin_status(entries, [], ["youtube"], [])

    assert len(result) == 1
    assert result[0].name == "meta"
    assert result[0].enabled is False


# ---------------------------------------------------------------------------
# PipResult
# ---------------------------------------------------------------------------


def test_pip_result_defaults() -> None:
    r = PipResult()
    assert r.success is False
    assert r.package == ""
    assert r.action == ""
    assert r.output == ""
    assert r.error == ""
