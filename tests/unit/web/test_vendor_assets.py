"""Committed browser assets match VENDOR.json and ship their licences (D23)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

VENDOR_DIR = Path(__file__).resolve().parents[3] / "src/sqlagent/adapters/web/static/vendor"
NOTICES = Path(__file__).resolve().parents[3] / "THIRD_PARTY_NOTICES.md"


def _manifest() -> dict[str, object]:
    return json.loads((VENDOR_DIR / "VENDOR.json").read_text(encoding="utf-8"))


def test_manifest_pins_the_three_packages() -> None:
    document = _manifest()

    assert document["schema"] == "sqlagent.vendor/v1"
    packages = document["packages"]
    assert isinstance(packages, list)
    assert {package["name"] for package in packages} == {"htmx.org", "htmx-ext-sse", "chart.js"}
    assert {package["version"] for package in packages} == {"2.0.11", "2.2.4", "4.6.1"}
    for package in packages:
        assert package["integrity"].startswith("sha512-")
        assert package["tarball"].startswith("https://registry.npmjs.org/")
        assert package["files"]


def test_files_exist_and_hashes_match() -> None:
    for package in _manifest()["packages"]:
        for entry in package["files"]:
            path = VENDOR_DIR / entry["path"]
            data = path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert len(data) == entry["bytes"]
        license_path = VENDOR_DIR / package["license_file"]
        assert license_path.is_file()
        assert license_path.stat().st_size > 200


def test_notices_include_every_licence() -> None:
    notices = NOTICES.read_text(encoding="utf-8")
    assert "htmx.org 2.0.11" in notices
    assert "htmx-ext-sse 2.2.4" in notices
    assert "chart.js 4.6.1" in notices
    assert "Zero-Clause BSD" in notices
    assert "MIT License" in notices
