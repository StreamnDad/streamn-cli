"""Shared fixtures for reeln tests."""

from __future__ import annotations

import logging
from collections.abc import Generator
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


@pytest.fixture()
def cli_runner() -> CliRunner:
    """Return a Typer CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture(autouse=True)
def reset_logging() -> None:
    """Clear logging handlers between tests."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def _reset_hook_registry() -> None:
    """Reset the plugin hook registry between tests for isolation."""
    from reeln.plugins.registry import reset_registry

    reset_registry()


@pytest.fixture(autouse=True)
def _no_real_plugins() -> Generator[None, None, None]:
    """Prevent real plugins from loading during tests.

    Without this, activate_plugins() loads plugins from the user's real
    config (e.g. google with create_livestream=true), causing side effects
    like creating actual YouTube livestreams on every test run.
    """
    with patch("reeln.plugins.loader.load_enabled_plugins", return_value={}):
        yield
