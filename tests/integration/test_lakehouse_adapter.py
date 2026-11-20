"""External lakehouse adapter: verified file, semantic layer, agent and CLI (T11/S31)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from sqlagent.adapters.cli.main import app
from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.adapters.semantic.manifest_repository import ManifestSemanticLayerRepository
from sqlagent.adapters.warehouse.lakehouse import (
    LAKEHOUSE_SCHEMA,
    LakehouseManifest,
    LakehouseWarehouse,
    load_manifest,
    open_lakehouse,
)
from sqlagent.application.ports import WarehouseLimits
from sqlagent.application.use_cases.ask import AskQuestion
from sqlagent.bootstrap import build_agent, build_runtime
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError, QueryTimeoutError, WarehouseUnavailable
from sqlagent.domain.models import Status
from sqlagent.domain.sql_policy import SqlPolicy

pytestmark = pytest.mark.integration

EMPLOYEE_COUNT = 1_500


def _manifest_document() -> dict[str, object]:
    return {
        "schema": LAKEHOUSE_SCHEMA,
        "name": "synthetic-lakehouse",
        "generated_at": "2026-11-20T10:00:00Z",
        "duckdb_file": "warehouse/synthetic.duckdb",
        "sha256": "0" * 64,
        "tables": [
            {
                "name": "departments",
                "description": "Company departments.",
                "columns": [
                    {
                        "name": "department_id",
                        "type": "VARCHAR",
                        "description": "Department identifier.",
                    },
                    {
                        "name": "department_name",
                        "type": "VARCHAR",
                        "description": "Human-readable department name.",
                        "lookupable": True,
                        "samples": ["Engineering", "Finance"],
                    },
                ],
            },
            {
                "name": "employees",
                "description": "One row per employee.",
                "columns": [
                    {
                        "name": "employee_id",
                        "type": "VARCHAR",
                        "description": "Employee identifier.",
                    },
                    {
                        "name": "department_id",
                        "type": "VARCHAR",
                        "description": "Department the employee belongs to.",
                    },
                    {
                        "name": "salary_usd",
                        "type": "DOUBLE",
                        "description": "Monthly salary in US dollars.",
                    },
                ],
            },
        ],
        "relationships": [{"from": "employees.department_id", "to": "departments.department_id"}],
        "language": "en",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_synthetic(tmp_path: Path) -> Path:
    db_path = tmp_path / "warehouse" / "synthetic.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute(
            "CREATE TABLE departments (department_id VARCHAR, department_name VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO departments VALUES (?, ?)",
            [("d1", "Engineering"), ("d2", "Finance"), ("d3", "Operations")],
        )
        connection.execute(
            "CREATE TABLE employees (employee_id VARCHAR, department_id VARCHAR, salary_usd DOUBLE)"
        )
        connection.execute(
            "INSERT INTO employees SELECT 'e' || i, 'd' || ((i % 3) + 1), "
            "1000.0 + i FROM range(?) t(i)",
            [EMPLOYEE_COUNT],
        )
    finally:
        connection.close()
    document = _manifest_document()
    document["sha256"] = _sha256(db_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    return manifest_path


def _final_sql(sql: str) -> str:
    return json.dumps({"plan": ["inspect", "query"], "action": "final_sql", "sql": sql})


def _narration(text: str) -> str:
    return json.dumps({"answer": text})


def test_manifest_semantic_layer_maps_external_schema(tmp_path: Path) -> None:
    manifest = load_manifest(_build_synthetic(tmp_path))

    semantic = ManifestSemanticLayerRepository(manifest).load()

    assert [table.name for table in semantic.tables] == ["departments", "employees"]
    assert semantic.metrics == ()
    assert semantic.glossary == ()
    assert semantic.relationships[0].from_ == "employees.department_id"
    assert semantic.relationships[0].on == ("employees.department_id = departments.department_id")
    assert semantic.lookupable_columns() == ("departments.department_name",)


def test_scripted_agent_answers_over_the_external_lakehouse(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    settings = Settings(
        llm_backend="replay",
        data_dir=tmp_path / "data",
        lakehouse_manifest=manifest_path,
    )
    llm = ScriptedLLM(
        [
            _final_sql("SELECT COUNT(*) AS n FROM employees"),
            _narration(f"There are {EMPLOYEE_COUNT} employees."),
        ]
    )

    agent = build_agent(settings, llm=llm)
    answer = AskQuestion(agent).execute("How many employees are there?")

    assert answer.status is Status.OK
    assert answer.result is not None
    assert answer.result.rows == ((EMPLOYEE_COUNT,),)
    prompt = "\n".join(str(message["content"]) for message in llm.calls[0].messages)
    assert "employees" in prompt
    assert "tenders" not in prompt
    assert "EXAMPLES" not in prompt


def test_runtime_uses_manifest_table_allowlist(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", lakehouse_manifest=_build_synthetic(tmp_path))

    runtime = build_runtime(settings)
    try:
        assert runtime.external is True
        assert runtime.lakehouse is not None
        assert runtime.lakehouse.name == "synthetic-lakehouse"
        assert runtime.warehouse.catalog().table_names() == {"departments", "employees"}
        assert runtime.fewshots == ()
        info = runtime.warehouse.info()
        assert info.tables == {"departments": 3, "employees": EMPLOYEE_COUNT}
        assert info.attribution == "External lakehouse: synthetic-lakehouse"
    finally:
        runtime.warehouse.close()


def test_tampered_duckdb_file_is_rejected(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    db_path = tmp_path / "warehouse" / "synthetic.duckdb"
    with db_path.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(WarehouseUnavailable, match="SHA-256 mismatch"):
        open_lakehouse(manifest_path)
    with pytest.raises(WarehouseUnavailable, match="SHA-256 mismatch"):
        build_runtime(Settings(data_dir=tmp_path / "data", lakehouse_manifest=manifest_path))


def test_manifest_column_missing_from_database_is_rejected(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["tables"][1]["columns"].append(
        {"name": "missing_column", "type": "VARCHAR", "description": "Not in the file."}
    )
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"employees\.missing_column"):
        open_lakehouse(manifest_path)


def test_manifest_type_mismatch_is_rejected(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["tables"][0]["columns"][0]["type"] = "INTEGER"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match="declares 'INTEGER'"):
        open_lakehouse(manifest_path)


def test_manifest_table_missing_from_database_is_rejected(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["tables"][0]["name"] = "absent_table"
    document["relationships"] = []
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match="absent_table"):
        open_lakehouse(manifest_path)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO departments VALUES ('d4', 'Legal')",
        "CREATE TABLE evil(x INTEGER)",
        "COPY (SELECT 1) TO '/tmp/sqlagent-lakehouse-evil.csv'",
        "ATTACH '/tmp/sqlagent-lakehouse-evil.duckdb'",
        "INSTALL httpfs",
        "SELECT * FROM read_csv('/etc/hostname')",
        "SET enable_external_access=true",
    ],
)
def test_external_database_keeps_the_same_lockdown(tmp_path: Path, statement: str) -> None:
    warehouse = open_lakehouse(_build_synthetic(tmp_path))
    try:
        with pytest.raises(duckdb.Error):
            warehouse.connection.execute(statement)
    finally:
        warehouse.close()


def test_external_database_query_timeout_is_typed(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    warehouse = open_lakehouse(manifest_path, WarehouseLimits(query_timeout_s=0.3))
    try:
        policy = SqlPolicy(warehouse.catalog().table_names())
        sql = (
            "SELECT SUM(LENGTH(a.employee_id) + LENGTH(b.employee_id) "
            "+ LENGTH(c.employee_id)) FROM employees a, employees b, employees c"
        )
        with pytest.raises(QueryTimeoutError):
            warehouse.execute(policy.validate(sql))
    finally:
        warehouse.close()


def test_doctor_validates_a_manifest_offline(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)

    result = CliRunner().invoke(app, ["doctor", "--offline", "--manifest", str(manifest_path)])

    assert result.exit_code == 0, result.output
    assert "manifest: valid synthetic-lakehouse" in result.output
    assert "warehouse: OK external" in result.output
    assert "warehouse OK" in result.output


def test_doctor_exits_three_for_a_tampered_duckdb(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    db_path = tmp_path / "warehouse" / "synthetic.duckdb"
    with db_path.open("ab") as handle:
        handle.write(b"tampered")

    result = CliRunner().invoke(app, ["doctor", "--offline", "--manifest", str(manifest_path)])

    assert result.exit_code == 3, result.output
    assert "SHA-256 mismatch" in result.output
    assert "warehouse broken" in result.output


def test_external_warehouse_does_not_expose_the_bundled_schema(tmp_path: Path) -> None:
    manifest = LakehouseManifest.model_validate({**_manifest_document(), "sha256": "b" * 64})
    # The semantic layer is derived only from the manifest (no bundled tables).
    semantic = ManifestSemanticLayerRepository(manifest).load()

    assert {table.name for table in semantic.tables} == {"departments", "employees"}
    assert semantic.column("tenders.tender_id") is None
    assert isinstance(manifest, LakehouseManifest)


def test_lakehouse_warehouse_is_usable_as_context_manager(tmp_path: Path) -> None:
    manifest_path = _build_synthetic(tmp_path)
    with LakehouseWarehouse(load_manifest(manifest_path), manifest_path) as warehouse:
        assert warehouse.catalog().table_names() == {"departments", "employees"}
