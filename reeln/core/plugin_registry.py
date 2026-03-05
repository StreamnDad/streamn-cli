"""Remote plugin registry: fetch, cache, version tracking, and pip-wrapping installer."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reeln.core.config import data_dir
from reeln.core.errors import RegistryError
from reeln.core.log import get_logger
from reeln.models.plugin import (
    PluginInfo,
    PluginStatus,
    RegistryEntry,
    dict_to_registry_entry,
    registry_entry_to_dict,
)

log: logging.Logger = get_logger(__name__)

DEFAULT_REGISTRY_URL: str = "https://raw.githubusercontent.com/StreamnDad/reeln-cli/main/registry/plugins.json"

_CACHE_TTL_SECONDS: int = 3600
_FETCH_TIMEOUT_SECONDS: int = 10


# ---------------------------------------------------------------------------
# Cache subsystem
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    """Return the registry cache directory."""
    return data_dir() / "registry"


def _cache_path() -> Path:
    """Return the path to the cached registry JSON."""
    return _cache_dir() / "plugins.json"


def _cache_meta_path() -> Path:
    """Return the path to the cache metadata file."""
    return _cache_dir() / "cache_meta.json"


def _is_cache_fresh() -> bool:
    """Check whether the registry cache is within the TTL window."""
    meta = _cache_meta_path()
    if not meta.is_file():
        return False
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        fetched_at = float(data.get("fetched_at", 0))
        return (time.time() - fetched_at) < _CACHE_TTL_SECONDS
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return False


def _read_cache() -> list[RegistryEntry] | None:
    """Read the cached registry entries. Returns ``None`` on miss or corruption."""
    cache = _cache_path()
    if not cache.is_file():
        return None
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        return _parse_registry_json(raw)
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def _write_cache(entries: list[RegistryEntry]) -> None:
    """Atomically write registry entries and metadata to the cache directory."""
    cache_d = _cache_dir()
    cache_d.mkdir(parents=True, exist_ok=True)

    # Write registry data
    data = {
        "registry_version": 1,
        "plugins": [registry_entry_to_dict(e) for e in entries],
    }
    content = json.dumps(data, indent=2) + "\n"
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=cache_d, text=True)
    try:
        with open(tmp_fd, "w") as tmp:
            tmp.write(content)
            tmp.flush()
        Path(tmp_name).replace(_cache_path())
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

    # Write metadata
    meta = {"fetched_at": time.time()}
    meta_content = json.dumps(meta) + "\n"
    tmp_fd2, tmp_name2 = tempfile.mkstemp(suffix=".tmp", dir=cache_d, text=True)
    try:
        with open(tmp_fd2, "w") as tmp:
            tmp.write(meta_content)
            tmp.flush()
        Path(tmp_name2).replace(_cache_meta_path())
    except BaseException:
        Path(tmp_name2).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Fetch subsystem
# ---------------------------------------------------------------------------


def _parse_registry_json(data: dict[str, Any]) -> list[RegistryEntry]:
    """Parse registry JSON into a list of ``RegistryEntry`` objects."""
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        raise KeyError("Missing or invalid 'plugins' key in registry data")
    return [dict_to_registry_entry(p) for p in plugins if isinstance(p, dict)]


def _fetch_remote(url: str) -> list[RegistryEntry]:
    """Fetch and parse the registry from a remote URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "reeln-cli"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Failed to fetch registry from {url}: {exc}") from exc
    try:
        return _parse_registry_json(raw)
    except (KeyError, TypeError) as exc:
        raise RegistryError(f"Invalid registry format from {url}: {exc}") from exc


def fetch_registry(url: str = "", *, force_refresh: bool = False) -> list[RegistryEntry]:
    """Fetch the plugin registry, using cache when appropriate.

    Uses the cached data when fresh. Falls back to stale cache on network
    errors. Raises ``RegistryError`` only when no data is available at all.
    """
    registry_url = url or DEFAULT_REGISTRY_URL

    if not force_refresh and _is_cache_fresh():
        cached = _read_cache()
        if cached is not None:
            return cached

    try:
        entries = _fetch_remote(registry_url)
        _write_cache(entries)
        return entries
    except RegistryError:
        # Fall back to stale cache if available
        cached = _read_cache()
        if cached is not None:
            log.warning("Using stale cache — remote registry unavailable")
            return cached
        raise


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------


def get_installed_version(package: str) -> str:
    """Return the installed version of a package, or ``""`` if not installed."""
    try:
        import importlib.metadata

        return importlib.metadata.version(package)
    except Exception:
        return ""


def get_pypi_version(package: str) -> str:
    """Fetch the latest version of a package from PyPI. Returns ``""`` on failure."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "reeln-cli"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("info", {}).get("version", ""))
    except Exception:
        return ""


def build_plugin_status(
    entries: list[RegistryEntry],
    installed_plugins: list[PluginInfo],
    enabled_list: list[str],
    disabled_list: list[str],
) -> list[PluginStatus]:
    """Merge registry info with installed state into unified status list."""
    registry_by_name: dict[str, RegistryEntry] = {e.name: e for e in entries}
    installed_by_name: dict[str, PluginInfo] = {p.name: p for p in installed_plugins}
    all_names = sorted(set(registry_by_name) | set(installed_by_name))

    result: list[PluginStatus] = []
    for name in all_names:
        reg = registry_by_name.get(name)
        inst = installed_by_name.get(name)

        is_installed = inst is not None
        installed_version = ""
        if is_installed:
            pkg = reg.package if reg else (inst.package if inst else "")
            if pkg:
                installed_version = get_installed_version(pkg)

        available_version = ""
        if reg:
            available_version = get_pypi_version(reg.package)

        # Determine enabled status
        enabled = False if name in disabled_list or (enabled_list and name not in enabled_list) else is_installed

        update_avail = bool(
            is_installed and installed_version and available_version and installed_version != available_version
        )

        result.append(
            PluginStatus(
                name=name,
                installed=is_installed,
                installed_version=installed_version,
                available_version=available_version,
                package=reg.package if reg else "",
                description=reg.description if reg else "",
                capabilities=list(reg.capabilities) if reg else (list(inst.capabilities) if inst else []),
                enabled=enabled,
                update_available=update_avail,
                homepage=reg.homepage if reg else "",
            )
        )
    return result


# ---------------------------------------------------------------------------
# Installer detection + pip runner
# ---------------------------------------------------------------------------


@dataclass
class PipResult:
    """Result of a pip install/update operation."""

    success: bool = False
    package: str = ""
    action: str = ""
    output: str = ""
    error: str = ""


def detect_installer() -> list[str]:
    """Detect the best available installer.

    Returns the command prefix targeting the *running* Python environment
    so that plugins are installed alongside reeln-cli (even when reeln is
    a uv tool and cwd contains a different ``.venv``).
    """
    if shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable]
    return [sys.executable, "-m", "pip", "install"]


def _run_pip(
    args: list[str],
    *,
    dry_run: bool = False,
    installer: str = "",
) -> PipResult:
    """Run a pip install/update command.

    On ``PermissionError``-like failures, auto-retries with ``--user``.
    """
    if installer == "uv":
        cmd_prefix = ["uv", "pip", "install"]
    elif installer == "pip":
        cmd_prefix = [sys.executable, "-m", "pip", "install"]
    else:
        cmd_prefix = detect_installer()

    full_cmd = cmd_prefix + args

    if dry_run:
        return PipResult(
            success=True,
            package=" ".join(args),
            action="dry-run",
            output=f"Would run: {' '.join(full_cmd)}",
        )

    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            return PipResult(
                success=True,
                package=" ".join(args),
                action="install",
                output=proc.stdout,
            )

        # Check for permission error and retry with --user
        if "permission" in proc.stderr.lower() and "--user" not in full_cmd:
            retry_cmd = [*cmd_prefix, "--user", *args]
            retry_proc = subprocess.run(
                retry_cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if retry_proc.returncode == 0:
                return PipResult(
                    success=True,
                    package=" ".join(args),
                    action="install",
                    output=retry_proc.stdout,
                )
            return PipResult(
                success=False,
                package=" ".join(args),
                action="install",
                error=retry_proc.stderr,
            )

        return PipResult(
            success=False,
            package=" ".join(args),
            action="install",
            error=proc.stderr,
        )
    except subprocess.TimeoutExpired:
        return PipResult(
            success=False,
            package=" ".join(args),
            action="install",
            error="Installation timed out",
        )
    except Exception as exc:
        return PipResult(
            success=False,
            package=" ".join(args),
            action="install",
            error=str(exc),
        )


def _resolve_entry(name: str, entries: list[RegistryEntry]) -> RegistryEntry:
    """Look up a registry entry by plugin name.

    Raises ``RegistryError`` if the plugin is not in the registry.
    """
    for entry in entries:
        if entry.name == name:
            return entry
    raise RegistryError(f"Plugin {name!r} not found in the registry")


def _resolve_package(name: str, entries: list[RegistryEntry]) -> str:
    """Map a plugin name to its PyPI package name.

    Raises ``RegistryError`` if the plugin is not in the registry.
    """
    return _resolve_entry(name, entries).package


def _resolve_install_target(entry: RegistryEntry) -> str:
    """Return the pip install target for a registry entry.

    Uses ``git+{homepage}`` when the homepage is a GitHub/GitLab URL,
    otherwise falls back to the PyPI package name.
    """
    homepage = entry.homepage
    if homepage and ("github.com/" in homepage or "gitlab.com/" in homepage):
        return f"git+{homepage}"
    return entry.package


def install_plugin(
    name: str,
    entries: list[RegistryEntry],
    *,
    dry_run: bool = False,
    installer: str = "",
) -> PipResult:
    """Install a plugin by name using the registry to resolve the package."""
    entry = _resolve_entry(name, entries)
    target = _resolve_install_target(entry)
    result = _run_pip([target], dry_run=dry_run, installer=installer)

    # Verify the package is actually installed (uv can return 0 for no-ops)
    if result.success and not dry_run and not get_installed_version(entry.package):
        return PipResult(
            success=False,
            package=entry.package,
            action="install",
            error=f"Package '{entry.package}' not found after install. "
            f"Check that the repository has a valid Python package.",
        )
    return result


def update_plugin(
    name: str,
    entries: list[RegistryEntry],
    *,
    dry_run: bool = False,
    installer: str = "",
) -> PipResult:
    """Update a plugin to the latest version."""
    entry = _resolve_entry(name, entries)
    target = _resolve_install_target(entry)
    result = _run_pip(["--upgrade", target], dry_run=dry_run, installer=installer)
    result = PipResult(
        success=result.success,
        package=entry.package,
        action="update" if not dry_run else "dry-run",
        output=result.output,
        error=result.error,
    )
    return result


def update_all_plugins(
    entries: list[RegistryEntry],
    installed: list[PluginInfo],
    *,
    dry_run: bool = False,
    installer: str = "",
) -> list[PipResult]:
    """Update all installed plugins that appear in the registry."""
    registry_names = {e.name for e in entries}
    results: list[PipResult] = []
    for plugin in installed:
        if plugin.name in registry_names:
            result = update_plugin(plugin.name, entries, dry_run=dry_run, installer=installer)
            results.append(result)
    return results
