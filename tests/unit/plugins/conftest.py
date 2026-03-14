"""Fixtures for plugin unit tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _no_real_plugins() -> Generator[None, None, None]:
    """Override the root conftest mock — plugin loader tests need the real function.

    The root conftest patches ``load_enabled_plugins`` to prevent real
    plugins from loading.  Plugin loader tests exercise the real function
    with their own mocked entry points, so the patch is disabled here.
    """
    yield
