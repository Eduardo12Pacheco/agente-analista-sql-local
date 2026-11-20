"""Release metadata and wheel contents stay consistent (S37, T13)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from sqlagent import __version__

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
MAX_WHEEL_BYTES = 12_000_000

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    uv = shutil.which("uv")
    if uv is None:  # pragma: no cover - uv is a documented prerequisite
        pytest.skip("uv is not available")
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [uv, "build", "--wheel", "--offline", "--out-dir", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def _project_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _dist_version() -> str:
    return __version__


def test_pyproject_and_package_versions_match() -> None:
    assert _project_version() == _dist_version()


def test_release_tag_matches_version_when_running_on_a_tag() -> None:
    if os.environ.get("GITHUB_REF_TYPE") != "tag":
        pytest.skip("not running in a tag build")
    tag = os.environ["GITHUB_REF_NAME"]
    assert tag == f"v{_project_version()}"


def test_wheel_contains_runtime_resources_and_no_eval_extras(wheel: Path) -> None:
    assert wheel.stat().st_size <= MAX_WHEEL_BYTES
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    required = {
        "sqlagent/resources/semantic_layer.yaml",
        "sqlagent/resources/fewshots.yaml",
        "sqlagent/resources/benchmark/v1/questions.yaml",
        "sqlagent/resources/benchmark/v1/benchmark.lock.json",
        "sqlagent/resources/warehouse/MANIFEST.json",
        "sqlagent/resources/recordings/qwen2.5-coder-7b/p1.jsonl",
        "sqlagent/adapters/web/templates/base.html",
        "sqlagent/adapters/web/templates/index.html",
        "sqlagent/adapters/web/static/vendor/VENDOR.json",
        "sqlagent/adapters/web/static/vendor/htmx.min.js",
        "sqlagent/adapters/web/static/vendor/sse.min.js",
        "sqlagent/adapters/web/static/vendor/chart.umd.min.js",
        "sqlagent/py.typed",
    }
    for table in (
        "awards",
        "buyers",
        "contracts",
        "suppliers",
        "tender_items",
        "tenders",
    ):
        required.add(f"sqlagent/resources/warehouse/{table}.parquet")

    missing = required - names
    assert not missing, f"wheel is missing runtime files: {sorted(missing)}"
    assert not any(name.startswith("eval/") for name in names)
    assert not any("recordings-extra" in name for name in names)
    assert not any(name.endswith("__pycache__") for name in names)


def test_wheel_metadata_version_matches_project(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        text = archive.read(metadata).decode("utf-8")

    assert f"Version: {_project_version()}" in text.splitlines()
    assert sys.version_info >= (3, 12)
