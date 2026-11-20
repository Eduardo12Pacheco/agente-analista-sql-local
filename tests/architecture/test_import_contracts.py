"""Architecture checks: import-linter contracts must guard the hexagon."""

from __future__ import annotations

import shutil
import subprocess

import pytest


@pytest.mark.architecture
def test_import_linter_contracts_hold() -> None:
    lint_imports = shutil.which("lint-imports")
    assert lint_imports is not None, "lint-imports must be installed (dependency group dev)"

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [lint_imports],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contracts: 2 kept, 0 broken" in result.stdout
