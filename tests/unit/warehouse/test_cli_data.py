"""`sqlagent data info|verify` CLI contract (T4)."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from sqlagent.adapters.cli.main import app
from sqlagent.adapters.warehouse.etl import BUNDLE_DIR

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ocds_mini"


def test_data_verify_and_info_on_the_bundle() -> None:
    runner = CliRunner()
    verify = runner.invoke(app, ["data", "verify"])
    assert verify.exit_code == 0, verify.output
    assert "tenders" in verify.output
    assert "121072" in verify.output.replace(",", "")

    info = runner.invoke(app, ["data", "info"])
    assert info.exit_code == 0, info.output
    assert "CC BY 3.0" in info.output
    assert "datosabiertos.compraspublicas.gob.ec" in info.output


def test_data_verify_fails_with_exit_code_2_on_a_broken_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(BUNDLE_DIR, bundle)
    (bundle / "tenders.parquet").write_bytes(b"broken")
    result = CliRunner().invoke(app, ["data", "verify", "--bundle", str(bundle)])
    assert result.exit_code == 2
    assert "tenders.parquet" in result.output


def test_data_build_from_a_local_source(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "data",
            "build",
            "--source",
            str(FIXTURES),
            "--out",
            str(tmp_path),
            "--allow-checksum-drift",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "MANIFEST.json").is_file()
    assert (tmp_path / "tenders.parquet").is_file()
