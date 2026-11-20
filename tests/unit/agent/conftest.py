"""Shared fixtures for agent state-machine tests (synthetic warehouse)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from sqlagent.adapters.semantic.fewshots_repository import load_fewshots
from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.application.agent.events import EventSink
from sqlagent.application.agent.machine import AnalystAgent
from sqlagent.application.ports import LLMPort, WarehouseLimits
from sqlagent.config import Settings
from sqlagent.domain.retrieval import Bm25Retriever, FewShot
from sqlagent.domain.semantic import SemanticColumn, SemanticLayer, SemanticTable
from sqlagent.domain.sql_policy import SqlPolicy


def _column(name: str, kind: str = "VARCHAR", lookupable: bool = False) -> SemanticColumn:
    return SemanticColumn(
        name=name,
        type=kind,
        description_en=f"{name} description",
        description_es=f"descripción de {name}",
        synonyms=(name,),
        lookupable=lookupable,
    )


@pytest.fixture(scope="session")
def semantic() -> SemanticLayer:
    return SemanticLayer(
        tables=(
            SemanticTable(
                name="buyers",
                description_en="Contracting entities",
                description_es="Entidades contratantes",
                synonyms=("compradores",),
                columns=(
                    _column("buyer_id"),
                    _column("buyer_name", lookupable=True),
                    _column("province", lookupable=True),
                ),
            ),
            SemanticTable(
                name="suppliers",
                description_en="Suppliers",
                description_es="Proveedores",
                columns=(
                    _column("supplier_id"),
                    _column("supplier_name", lookupable=True),
                    _column("supplier_kind"),
                ),
            ),
            SemanticTable(
                name="tenders",
                description_en="Procurement processes",
                description_es="Procesos de contratación",
                synonyms=("procesos",),
                columns=(
                    _column("tender_id"),
                    _column("release_date", "DATE"),
                    _column("buyer_id"),
                    _column("title"),
                    _column("description"),
                    _column("procurement_method", lookupable=True),
                    _column("procurement_type", lookupable=True),
                    _column("planned_amount_usd", "DOUBLE"),
                    _column("status", lookupable=True),
                    _column("category", lookupable=True),
                    _column("is_competitive", "BOOLEAN"),
                ),
            ),
            SemanticTable(
                name="awards",
                description_en="Awards",
                description_es="Adjudicaciones",
                columns=(
                    _column("tender_id"),
                    _column("award_id"),
                    _column("supplier_id"),
                    _column("amount_usd", "DOUBLE"),
                    _column("status"),
                ),
            ),
            SemanticTable(
                name="contracts",
                description_en="Contracts",
                description_es="Contratos",
                columns=(
                    _column("contract_id"),
                    _column("tender_id"),
                    _column("amount_usd", "DOUBLE"),
                    _column("status", lookupable=True),
                ),
            ),
            SemanticTable(
                name="tender_items",
                description_en="Tender items",
                description_es="Ítems de procesos",
                columns=(_column("item_id"), _column("tender_id"), _column("description")),
            ),
        ),
        data_quirks=("planned amounts are NULL for subasta inversa",),
    )


@pytest.fixture(scope="session")
def fewshots() -> tuple[FewShot, ...]:
    return load_fewshots()


@pytest.fixture
def warehouse(tmp_path: Path) -> DuckDbWarehouse:
    path = tmp_path / "agent.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE buyers(buyer_id VARCHAR, buyer_name VARCHAR, province VARCHAR, "
            "canton VARCHAR)"
        )
        con.execute(
            "INSERT INTO buyers VALUES "
            "('1712345678001', 'INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL', 'PICHINCHA', 'QUITO'),"
            "('1798765432001', 'MUNICIPIO DE CUENCA', 'AZUAY', 'CUENCA')"
        )
        con.execute(
            "CREATE TABLE suppliers(supplier_id VARCHAR, supplier_name VARCHAR, "
            "supplier_kind VARCHAR, province VARCHAR)"
        )
        con.execute(
            "INSERT INTO suppliers VALUES "
            "('1790012345001', 'ACME CONSTRUCCIONES S.A.', 'company', 'PICHINCHA'),"
            "('PN-000001', 'Persona natural PN-000001', 'natural_person', 'GUAYAS')"
        )
        con.execute(
            "CREATE TABLE tenders(tender_id VARCHAR, process_code VARCHAR, release_date DATE, "
            "buyer_id VARCHAR, title VARCHAR, description VARCHAR, procurement_method VARCHAR, "
            "procurement_type VARCHAR, planned_amount_usd DOUBLE, status VARCHAR, "
            "category VARCHAR, is_competitive BOOLEAN)"
        )
        con.execute(
            "INSERT INTO tenders VALUES "
            "('t1','CE-1',DATE '2021-01-05','1712345678001','Hospital supplies',"
            "'medical equipment','direct','contratacion_directa',1000.0,'complete','goods',false),"
            "('t2','CE-2',DATE '2021-02-10','1712345678001','Road works',"
            "'road repair','open','subasta_inversa',2000.0,'active','works',true),"
            "('t3','CE-3',DATE '2021-03-15','1798765432001','Software license',"
            "'software','selective','cotizacion',3000.0,'complete','services',true)"
        )
        con.execute(
            "CREATE TABLE awards(tender_id VARCHAR, award_id VARCHAR, supplier_id VARCHAR, "
            "amount_usd DOUBLE, status VARCHAR)"
        )
        con.execute(
            "INSERT INTO awards VALUES "
            "('t1','a1','1790012345001',900.0,'active'),"
            "('t2','a2','PN-000001',1500.0,NULL),"
            "('t3','a3','1790012345001',2500.0,'active')"
        )
        con.execute(
            "CREATE TABLE contracts(contract_id VARCHAR, tender_id VARCHAR, award_id VARCHAR, "
            "status VARCHAR, amount_usd DOUBLE, signed_date DATE, duration_days INTEGER)"
        )
        con.execute(
            "INSERT INTO contracts VALUES "
            "('c1','t1','a1','active',900.0,DATE '2021-02-01',30),"
            "('c2','t3','a3','terminated',2500.0,DATE '2021-04-01',60)"
        )
        con.execute(
            "CREATE TABLE tender_items(item_id VARCHAR, tender_id VARCHAR, description VARCHAR, "
            "quantity DOUBLE, unit_name VARCHAR, unit_price_usd DOUBLE, cpc_code VARCHAR, "
            "cpc_description VARCHAR)"
        )
        con.execute(
            "INSERT INTO tender_items VALUES "
            "('i1','t1','mask',10.0,'unit',5.0,'331','medical'),"
            "('i2','t1','gloves',20.0,'unit',2.0,'331','medical')"
        )
    finally:
        con.close()
    instance = DuckDbWarehouse(path, WarehouseLimits())
    yield instance
    instance.close()


@pytest.fixture
def policy(warehouse: DuckDbWarehouse) -> SqlPolicy:
    return SqlPolicy(catalog_tables=warehouse.catalog().table_names(), max_rows=1000)


@pytest.fixture
def retriever(semantic: SemanticLayer, fewshots: tuple[FewShot, ...]) -> Bm25Retriever:
    return Bm25Retriever(semantic, fewshots)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", llm_backend="replay")


@pytest.fixture
def make_agent(
    warehouse: DuckDbWarehouse,
    policy: SqlPolicy,
    retriever: Bm25Retriever,
    semantic: SemanticLayer,
    settings: Settings,
    fewshots: tuple[FewShot, ...],
) -> Callable[..., AnalystAgent]:
    def factory(
        llm: LLMPort,
        *,
        narrate: bool = True,
        sink: EventSink | None = None,
        **overrides: object,
    ) -> AnalystAgent:
        config = settings.model_copy(update=overrides)
        return AnalystAgent(
            llm,
            warehouse,
            policy,
            retriever,
            semantic,
            config,
            sink=sink,
            narrate=narrate,
            fewshots=fewshots,
        )

    return factory
