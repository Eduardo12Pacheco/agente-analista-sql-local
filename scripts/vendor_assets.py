#!/usr/bin/env python3
"""Vendor the web UI's browser assets from npm tarballs (D23/S29).

For every package the script downloads the pinned tarball from the npm registry,
verifies the registry's ``dist.integrity`` (SHA-512), extracts only the files the
UI needs, copies the package licence and writes ``VENDOR.json`` plus the
third-party notices section.  No CDN is involved at runtime and the script is
idempotent: rerunning it reproduces byte-identical assets.
"""

# ruff: noqa: S310 - every URL is a pinned https registry/repository constant.

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
VENDOR_DIR: Final = ROOT / "src/sqlagent/adapters/web/static/vendor"
NOTICES_PATH: Final = ROOT / "THIRD_PARTY_NOTICES.md"
USER_AGENT: Final = "sqlagent-vendor-assets/1.0"
HTMX_EXTENSIONS_LICENSE_URL: Final = (
    "https://raw.githubusercontent.com/bigskysoftware/htmx-extensions/v2.2.4/LICENSE"
)

NOTICES_START: Final = "<!-- VENDOR:START -->"
NOTICES_END: Final = "<!-- VENDOR:END -->"


@dataclass(frozen=True)
class Package:
    """One npm package to vendor."""

    name: str
    version: str
    files: tuple[tuple[str, str], ...]  # (member path, output file name)
    license_members: tuple[str, ...] = ("LICENSE", "LICENSE.md")
    fallback_license_url: str | None = None


PACKAGES: Final[tuple[Package, ...]] = (
    Package(
        name="htmx.org",
        version="2.0.11",
        files=(("package/dist/htmx.min.js", "htmx.min.js"),),
    ),
    Package(
        name="htmx-ext-sse",
        version="2.2.4",
        files=(("package/dist/sse.min.js", "sse.min.js"),),
        fallback_license_url=HTMX_EXTENSIONS_LICENSE_URL,
    ),
    Package(
        name="chart.js",
        version="4.6.1",
        files=(("package/dist/chart.umd.min.js", "chart.umd.min.js"),),
    ),
)


def _fetch(url: str, *, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _fetch_json(url: str) -> dict[str, Any]:
    payload = json.loads(_fetch(url).decode("utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"unexpected registry response from {url}")
    return payload


def verify_integrity(data: bytes, integrity: str) -> None:
    """Verify a ``dist.integrity`` value (the strongest SHA-512 entry)."""

    entries = [entry for entry in integrity.split() if entry.startswith("sha512-")]
    if not entries:
        raise SystemExit(f"no sha512 entry in integrity value {integrity!r}")
    expected = entries[0].split("-", 1)[1]
    actual = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    if actual != expected:
        raise SystemExit("npm tarball integrity mismatch")


def extract_members(tarball: bytes, members: tuple[tuple[str, str], ...]) -> dict[str, bytes]:
    """Return ``{output name: bytes}`` for the requested tarball members."""

    extracted: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        by_name = {member.name: member for member in archive.getmembers()}
        for source, target in members:
            member = by_name.get(source)
            if member is None:
                raise SystemExit(f"missing tarball member {source}")
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"cannot read tarball member {source}")
            extracted[target] = handle.read()
    return extracted


def _license_bytes(package: Package, tarball: bytes) -> tuple[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        by_name = {member.name: member for member in archive.getmembers()}
        for candidate in package.license_members:
            member = by_name.get(f"package/{candidate}")
            if member is not None and member.isfile():
                handle = archive.extractfile(member)
                if handle is not None:
                    return candidate, handle.read()
    if package.fallback_license_url:
        return "LICENSE (upstream repository)", _fetch(package.fallback_license_url)
    raise SystemExit(f"no licence file found in {package.name}@{package.version}")


def _notices_section(packages: list[dict[str, Any]]) -> str:
    lines = [
        NOTICES_START,
        "## Vendored web assets",
        "",
        "These browser assets are copied verbatim from the npm packages below and",
        "served from `/static/vendor/`; no CDN is used at runtime.",
        "",
    ]
    for package in packages:
        lines.extend(
            [
                f"### {package['name']} {package['version']}",
                "",
                f"- Integrity: `{package['integrity']}`",
                f"- Tarball: {package['tarball']}",
                f"- Files: {', '.join(item['path'] for item in package['files'])}",
                f"- Licence: `{package['license_file']}`",
                "",
                "```text",
                package["license_text"].strip(),
                "```",
                "",
            ]
        )
    lines.append(NOTICES_END)
    return "\n".join(lines) + "\n"


def update_notices(packages: list[dict[str, Any]]) -> None:
    current = NOTICES_PATH.read_text(encoding="utf-8")
    section = _notices_section(packages)
    if NOTICES_START in current and NOTICES_END in current:
        before = current.split(NOTICES_START, 1)[0]
        after = current.split(NOTICES_END, 1)[1]
        updated = f"{before.rstrip()}\n\n{section}{after.lstrip()}"
    else:
        updated = f"{current.rstrip()}\n\n{section}"
    NOTICES_PATH.write_text(updated, encoding="utf-8")


def vendor(check: bool = False) -> int:
    """Download, verify and write every vendored asset."""

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    licenses_dir = VENDOR_DIR / "licenses"
    licenses_dir.mkdir(exist_ok=True)
    report: list[dict[str, Any]] = []
    for package in PACKAGES:
        metadata = _fetch_json(f"https://registry.npmjs.org/{package.name}/{package.version}")
        version = str(metadata.get("version", ""))
        if version != package.version:
            raise SystemExit(f"registry returned {version}, expected {package.version}")
        dist = metadata.get("dist", {})
        tarball_url = str(dist.get("tarball", ""))
        integrity = str(dist.get("integrity", ""))
        tarball = _fetch(tarball_url)
        verify_integrity(tarball, integrity)
        extracted = extract_members(tarball, package.files)
        _license_name, license_bytes = _license_bytes(package, tarball)
        license_path = licenses_dir / f"{package.name.lower().replace('.', '-')}.txt"
        license_path.write_bytes(license_bytes)
        files: list[dict[str, Any]] = []
        for target, data in extracted.items():
            destination = VENDOR_DIR / target
            if check:
                if destination.read_bytes() != data:
                    raise SystemExit(f"{destination} is stale; rerun scripts/vendor_assets.py")
            else:
                destination.write_bytes(data)
            files.append(
                {
                    "path": target,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
        report.append(
            {
                "name": package.name,
                "version": package.version,
                "integrity": integrity,
                "tarball": tarball_url,
                "files": files,
                "license_file": license_path.relative_to(VENDOR_DIR).as_posix(),
                "license_text": license_bytes.decode("utf-8", errors="replace"),
            }
        )
        print(f"verified {package.name}@{package.version} ({len(files)} file(s))")

    document = {
        "schema": "sqlagent.vendor/v1",
        "packages": [
            {key: value for key, value in package.items() if key != "license_text"}
            for package in report
        ],
    }
    manifest_path = VENDOR_DIR / "VENDOR.json"
    manifest = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if check:
        if manifest_path.read_text(encoding="utf-8") != manifest:
            raise SystemExit(f"{manifest_path} is stale; rerun scripts/vendor_assets.py")
    else:
        manifest_path.write_text(manifest, encoding="utf-8")
        update_notices(report)
    print(f"wrote {manifest_path.relative_to(ROOT)} and third-party notices")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the committed assets match the pinned registry tarballs.",
    )
    arguments = parser.parse_args()
    return vendor(check=arguments.check)


if __name__ == "__main__":
    raise SystemExit(main())
