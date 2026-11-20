"""BM25 retrieval over the bundled bilingual semantic layer (S7/D13)."""

from __future__ import annotations

import pytest

from sqlagent.adapters.semantic.yaml_repository import YamlSemanticLayerRepository
from sqlagent.domain.language import Language
from sqlagent.domain.retrieval import Bm25Retriever, FewShot, tokenize
from sqlagent.domain.semantic import SemanticLayer

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def layer() -> SemanticLayer:
    return YamlSemanticLayerRepository().load()


@pytest.fixture(scope="module")
def retriever(layer: SemanticLayer) -> Bm25Retriever:
    return Bm25Retriever(layer)


def test_tokenizer_folds_accents_drops_stopwords_and_stems() -> None:
    """ES/EN questions normalise to comparable stemmed tokens."""

    spanish = tokenize("¿Cuántos CONTRATOS hay en la provincia?")
    assert "contrato" in spanish
    assert "cuantos" not in spanish
    assert "provincia" in spanish

    english = tokenize("How many TENDERS are there?")
    assert "tender" in english
    assert "how" not in english
    assert "there" not in english

    assert tokenize("") == ()
    assert tokenize("   ¿¡!?   ") == ()


def test_tokenizer_is_accent_insensitive() -> None:
    assert tokenize("Cuántos contratos") == tokenize("cuantos contratos")
    assert tokenize("GESTIÓN") == tokenize("gestion")


TABLE_CASES: tuple[tuple[str, frozenset[str]], ...] = (
    ("How many tenders are in the database?", frozenset({"tenders"})),
    ("¿Cuántos procesos de contratación hay?", frozenset({"tenders"})),
    ("¿Cuál es el monto total adjudicado en dólares?", frozenset({"awards"})),
    ("Total awarded amount per province", frozenset({"awards", "tenders", "buyers"})),
    ("monto total adjudicado por provincia", frozenset({"awards", "tenders", "buyers"})),
    ("Top 10 suppliers by total awarded amount", frozenset({"awards", "suppliers"})),
    (
        "¿Cuáles son los 5 proveedores con más contratos?",
        frozenset({"contracts", "suppliers"}),
    ),
    ("¿Cuántos procesos se publicaron por mes?", frozenset({"tenders"})),
    ("What percentage of tenders were competitive?", frozenset({"tenders"})),
    (
        "¿Qué entidad contratante tiene el mayor monto adjudicado en cada provincia?",
        frozenset({"buyers", "awards", "tenders"}),
    ),
    ("¿Cuántos procesos publicó el IESS?", frozenset({"buyers", "tenders"})),
    ("productos más comprados", frozenset({"tender_items"})),
    ("Which items were bought most often?", frozenset({"tender_items"})),
    ("distinct suppliers count", frozenset({"suppliers"})),
    ("número de compradores distintos", frozenset({"buyers"})),
    ("average award amount", frozenset({"awards"})),
    ("average number of tenderers", frozenset({"tenders"})),
    ("contracts signed in 2021", frozenset({"contracts"})),
    ("total contracted amount", frozenset({"contracts"})),
    ("works procurement category", frozenset({"tenders"})),
    ("electronic catalogue purchases", frozenset({"tenders"})),
    ("personas naturales proveedores", frozenset({"suppliers"})),
    ("provinces with most buyers", frozenset({"buyers"})),
    ("cpc code of purchased items", frozenset({"tender_items"})),
)


@pytest.mark.parametrize(("question", "expected"), TABLE_CASES)
def test_table_recall_on_handwritten_cases(
    retriever: Bm25Retriever, question: str, expected: frozenset[str]
) -> None:
    """Every handwritten ES/EN case retrieves at least its expected tables (S7)."""

    result = retriever.search(question)
    assert expected <= set(result.tables), (question, result.tables)


def test_retrieval_includes_join_bridges(retriever: Bm25Retriever) -> None:
    """Selecting awards and buyers also pulls in the tenders bridge table."""

    result = retriever.search("monto total adjudicado por provincia")
    assert set(result.tables) >= {"awards", "buyers", "tenders"}
    assert len(result.tables) <= 4


def test_accent_insensitive_questions_return_the_same_context(
    retriever: Bm25Retriever, layer: SemanticLayer
) -> None:
    accented = retriever.search("¿Cuántos contratos hay?")
    plain = retriever.search("cuantos contratos hay")

    assert accented.tables == plain.tables
    assert [doc.name for doc in accented.docs] == [doc.name for doc in plain.docs]
    assert accented.render_context(layer) == plain.render_context(layer)


def test_retrieval_is_deterministic(retriever: Bm25Retriever, layer: SemanticLayer) -> None:
    first = retriever.search("top suppliers by amount")
    second = retriever.search("top suppliers by amount")

    assert first.tables == second.tables
    assert [doc.name for doc in first.docs] == [doc.name for doc in second.docs]
    assert first.render_context(layer) == second.render_context(layer)


def test_empty_question_falls_back_to_core_tables(retriever: Bm25Retriever) -> None:
    result = retriever.search("   ")

    assert result.tables == ("tenders", "awards")
    assert result.metrics


def test_empty_semantic_layer_is_handled() -> None:
    result = Bm25Retriever(SemanticLayer()).search("how many tenders")

    assert result.tables == ()
    assert result.metrics == ()
    assert result.docs == ()


def test_metrics_belong_to_selected_tables(retriever: Bm25Retriever, layer: SemanticLayer) -> None:
    result = retriever.search("¿Cuál es el monto total adjudicado en dólares?")
    by_name = {metric.name: metric for metric in layer.metrics}

    assert "total_awarded_usd" in {metric.name for metric in result.metrics}
    for metric in result.metrics:
        assert set(metric.tables) <= set(result.tables)
    assert by_name["total_awarded_usd"] in result.metrics


def test_few_shots_are_ranked_and_returned(layer: SemanticLayer) -> None:
    fewshots = (
        FewShot(
            question="How many contracts were signed per supplier?",
            sql="SELECT s.supplier_name, COUNT(*) FROM contracts c "
            "JOIN suppliers s ON s.supplier_id = c.contract_id GROUP BY 1",
            language=Language.EN,
            tables=("contracts", "suppliers"),
        ),
        FewShot(
            question="¿Cuántos procesos publicó cada comprador?",
            sql="SELECT b.buyer_name, COUNT(*) FROM tenders t "
            "JOIN buyers b USING (buyer_id) GROUP BY 1",
            language=Language.ES,
            tables=("tenders", "buyers"),
        ),
    )
    retriever = Bm25Retriever(layer, fewshots=fewshots)

    result = retriever.search("contracts signed per supplier")

    assert result.fewshots
    assert result.fewshots[0].language is Language.EN
    assert "contracts" in result.fewshots[0].tables
    assert result.render_context(layer)
