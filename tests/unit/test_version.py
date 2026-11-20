"""Version metadata stays consistent between the package and pyproject.toml."""

from __future__ import annotations

import re
from importlib.metadata import version

import pytest

from sqlagent import __version__


@pytest.mark.unit
def test_version_matches_installed_metadata() -> None:
    assert __version__ == version("local-sql-analyst-agent")


@pytest.mark.unit
def test_version_is_pep440_dev_release() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?", __version__)
    assert __version__.startswith("0.1.0")
