"""Documentation acceptance checks (T14/S38).

These tests keep the READMEs, docs and ADRs honest: relative links must
resolve, the Spanish README mirrors the English section order, every settings
field is documented, the required ADRs exist and the SERCOP attribution plus
every committed warehouse checksum appears in ``docs/DATA.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sqlagent.config import Settings

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
README_ES = ROOT / "README.es.md"
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
MANIFEST = ROOT / "src" / "sqlagent" / "resources" / "warehouse" / "MANIFEST.json"

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)
REQUIRED_ADRS = tuple(range(1, 10))
ADR_SECTIONS = ("Context", "Decision", "Consequences", "Alternatives considered")

SCREENSHOTS = ("hero-light.png", "hero-dark.png", "answer-chart.png", "empty-state.png")
GIF = "demo.gif"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _local_targets(document: Path) -> list[str]:
    """Return local relative link/image targets from a Markdown document."""

    targets: list[str] = []
    for raw in LINK_RE.findall(_read(document)):
        target = raw.strip()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        target = target.split("#", 1)[0].split("?", 1)[0]
        if target:
            targets.append(target)
    return targets


@pytest.mark.unit
def test_readme_budget_and_sections() -> None:
    text = _read(README)
    assert len(text.splitlines()) <= 150
    for marker in ("<!-- METRICS:START -->", "<!-- METRICS:END -->"):
        assert marker in text
    for section in (
        "## What it does",
        "## Why it is interesting",
        "## Architecture",
        "## Quickstart",
        "## Results",
        "## Data and attribution",
        "## Documentation",
        "## Limitations",
    ):
        assert section in text


@pytest.mark.unit
def test_readme_has_badges_hero_and_media_links() -> None:
    text = _read(README)
    for badge in ("badge.svg", "license-MIT", "python-3.12", "managed%20with-uv"):
        assert badge in text
    assert "docs/assets/demo.gif" in text
    assert "docs/assets/hero-light.png" in text
    assert "README.es.md" in text


@pytest.mark.unit
def test_spanish_readme_mirrors_heading_order() -> None:
    english = _read(README)
    spanish = _read(README_ES)
    assert len(HEADING_RE.findall(spanish)) == len(HEADING_RE.findall(english))
    assert "# local-sql-analyst-agent" in spanish
    for marker in ("<!-- METRICS:START -->", "<!-- METRICS:END -->"):
        assert marker in spanish
    assert "SERCOP" in spanish


@pytest.mark.unit
@pytest.mark.parametrize("document", [README, README_ES])
def test_relative_links_and_images_resolve(document: Path) -> None:
    missing = [target for target in _local_targets(document) if not (ROOT / target).exists()]
    assert missing == []


@pytest.mark.unit
def test_docs_relative_links_resolve() -> None:
    missing: list[str] = []
    for document in sorted(DOCS.rglob("*.md")):
        for target in _local_targets(document):
            if not (document.parent / target).exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    for name in ("CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md"):
        document = ROOT / name
        for target in _local_targets(document):
            if not (ROOT / target).exists():
                missing.append(f"{name} -> {target}")
    assert missing == []


@pytest.mark.unit
def test_every_settings_field_is_documented() -> None:
    text = _read(DOCS / "CONFIGURATION.md")
    for name in Settings.model_fields:
        assert f"SQLAGENT_{name.upper()}" in text, name


@pytest.mark.unit
def test_required_adrs_and_sections() -> None:
    for number in REQUIRED_ADRS:
        matches = sorted((DOCS / "adr").glob(f"{number:04d}-*.md"))
        assert len(matches) == 1, f"ADR-{number:04d} missing or duplicated"
        text = _read(matches[0])
        for section in ADR_SECTIONS:
            assert f"## {section}" in text, f"{matches[0].name} lacks {section}"
    index = _read(DOCS / "adr" / "index.md")
    for number in REQUIRED_ADRS:
        assert f"{number:04d}" in index


@pytest.mark.unit
def test_data_doc_contains_attribution_and_every_manifest_hash() -> None:
    data = _read(DOCS / "DATA.md")
    assert "SERCOP" in data
    assert "CC BY 3.0" in data
    assert "https://datosabiertos.compraspublicas.gob.ec" in data
    manifest = json.loads(_read(MANIFEST))
    hashes = {manifest["source"]["tarball_sha256"]}
    hashes.update(member["sha256"] for member in manifest["source"]["members"].values())
    hashes.update(table["sha256"] for table in manifest["tables"].values())
    missing = sorted(digest for digest in hashes if digest not in data)
    assert missing == []


@pytest.mark.unit
def test_screenshots_and_gif_are_committed() -> None:
    for name in SCREENSHOTS:
        path = ASSETS / name
        assert path.is_file(), name
        assert path.stat().st_size > 20_000, name
    gif = ASSETS / GIF
    assert gif.is_file()
    assert gif.stat().st_size <= 3 * 1024 * 1024


@pytest.mark.unit
def test_no_owner_home_paths_in_public_docs() -> None:
    public = [README, README_ES, *DOCS.rglob("*.md"), ROOT / "CONTRIBUTING.md"]
    offenders = [str(path.relative_to(ROOT)) for path in public if "/home/" in _read(path)]
    assert offenders == []


@pytest.mark.unit
def test_limitations_are_honest() -> None:
    text = _read(README)
    limitations = text.split("## Limitations", 1)[1]
    for phrase in ("single warehouse", "n = 72", "wide", "lexical", "one machine"):
        assert phrase.lower() in limitations.lower(), phrase
