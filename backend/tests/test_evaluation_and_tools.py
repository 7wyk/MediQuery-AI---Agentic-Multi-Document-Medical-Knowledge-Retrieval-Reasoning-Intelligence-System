from __future__ import annotations

import pytest

from app.evaluation import metrics
from app.services.tools import execute_tool, list_tools


def test_retrieval_metrics():
    assert metrics.precision_at_k(["a", "b", "c"], ["a", "c"]) == pytest.approx(2 / 3)
    assert metrics.recall_at_k(["a"], ["a", "b"]) == pytest.approx(0.5)
    assert metrics.precision_at_k([], ["a"]) == 0.0
    assert metrics.recall_at_k(["a"], []) == 0.0


def test_answer_and_context_relevance():
    context = ["Metformin lowers glucose", "Insulin therapy for diabetes"]
    assert metrics.context_relevance(context, ["metformin", "glucose"]) == 1.0
    assert metrics.context_relevance(context, ["metformin", "oncology"]) == 0.5
    assert metrics.answer_relevance("Metformin is first line", ["metformin"]) == 1.0


def test_faithfulness_and_hallucination():
    claims = [{"supported": True}, {"supported": False}]
    assert metrics.faithfulness(claims) == 0.5
    assert metrics.hallucination_rate(claims) == 0.5
    assert metrics.faithfulness([]) == 0.0


def test_citation_correctness_checks_document_and_page():
    citations = [
        {"kind": "document", "filename": "Diabetes_Management.pdf", "page": 2},
        {"kind": "document", "filename": "other.pdf", "page": 9},
        {"kind": "web", "url": "https://pubmed.ncbi.nlm.nih.gov/1/"},
    ]
    score = metrics.citation_correctness(
        citations,
        expected_filenames=["Diabetes_Management.pdf"],
        expected_pages=[2],
    )
    assert score == pytest.approx(2 / 3)


def test_groundedness_and_abstention():
    citations = [{"kind": "document", "filename": "a.pdf"}]
    claims = [{"supported": True, "evidence_indexes": [1]}]
    assert metrics.groundedness(citations, claims) == 1.0
    assert metrics.groundedness([], []) == 0.0
    assert metrics.abstention_correctness(True, True) == 1.0
    assert metrics.abstention_correctness(True, False) == 0.0


def test_aggregate_by_category():
    records = [
        {"category": "numerical", "metrics": {"faithfulness": 1.0, "answer_relevance": 0.5}},
        {"category": "numerical", "metrics": {"faithfulness": 0.0, "answer_relevance": 0.5}},
        {"category": "non_medical", "metrics": {"faithfulness": 0.5}},
    ]
    overall = metrics.aggregate(records)
    assert overall["faithfulness"] == pytest.approx(0.5)
    grouped = metrics.aggregate_by_category(records)
    assert grouped["numerical"]["faithfulness"] == pytest.approx(0.5)
    assert grouped["non_medical"]["faithfulness"] == pytest.approx(0.5)


def test_tool_registry_is_allowlisted():
    names = {tool["name"] for tool in list_tools()}
    assert names == {"pubmed_search", "fda_drug_label", "icd10_lookup"}
    for tool in list_tools():
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["external"] is True


@pytest.mark.asyncio
async def test_unknown_tool_and_invalid_arguments_are_rejected():
    unknown = await execute_tool(name="rm_rf", arguments={})
    assert unknown["ok"] is False

    invalid = await execute_tool(name="pubmed_search", arguments={"query": "x"})
    assert invalid["ok"] is False
    assert "Invalid tool input" in invalid["error"]
