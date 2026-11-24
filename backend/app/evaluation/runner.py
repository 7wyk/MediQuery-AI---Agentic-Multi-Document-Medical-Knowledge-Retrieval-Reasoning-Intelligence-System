"""Reproducible offline RAG evaluation runner.

Usage (from ``backend/``):

    python -m app.evaluation.runner --user-email you@example.com --output report.json

The runner executes the question set in ``dataset.json`` against the user's
indexed documents, computes retrieval/answer/grounding metrics, persists each
result to ``evaluation_records`` and prints an aggregate report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from app.database import SessionLocal
from app.evaluation import metrics
from app.models.analytics import EvaluationRecord
from app.models.user import User
from app.services.agentic_rag import run_rag
from app.services.domain_validation import validate_query

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).with_name("dataset.json")


def load_dataset(path: Path = DATASET_PATH) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


async def evaluate_case(db, user_id: int, case: Dict, run_id: str) -> Dict:
    question = case["question"]
    validation = await validate_query(question)
    if not validation.is_medical:
        result_payload = {
            "answer": "",
            "abstained": True,
            "sources": [],
            "claims": [],
            "evidence_status": "rejected_domain",
        }
    else:
        result = await run_rag(
            db,
            user_id=user_id,
            question=question,
            allow_web_search=False,
            mode="agentic",
        )
        result_payload = {
            "answer": result.answer,
            "abstained": result.insufficient,
            "sources": [citation.model_dump() for citation in result.sources],
            "claims": [claim.model_dump() for claim in result.metadata.claims],
            "evidence_status": result.evidence_status,
        }

    document_citations = [
        citation for citation in result_payload["sources"] if citation.get("kind") == "document"
    ]
    retrieved_ids = [
        f"{citation.get('filename')}::{citation.get('page')}" for citation in document_citations
    ]
    expected_ids = [
        f"{filename}::{page}"
        for filename in case.get("expected_filenames", [])
        for page in (case.get("expected_pages") or [None])
    ]
    retrieved_texts = [citation.get("snippet", "") for citation in document_citations]
    claims = result_payload["claims"]
    computed = {
        "retrieval_precision": metrics.precision_at_k(
            retrieved_ids, expected_ids
        )
        if case.get("expected_pages")
        else metrics.context_relevance(retrieved_texts, case.get("expected_keywords", [])),
        "retrieval_recall": metrics.recall_at_k(retrieved_ids, expected_ids)
        if case.get("expected_pages")
        else metrics.context_relevance(retrieved_texts, case.get("expected_keywords", [])),
        "context_relevance": metrics.context_relevance(
            retrieved_texts, case.get("expected_keywords", [])
        ),
        "answer_relevance": metrics.answer_relevance(
            result_payload["answer"], case.get("expected_keywords", [])
        ),
        "faithfulness": metrics.faithfulness(claims),
        "groundedness": metrics.groundedness(result_payload["sources"], claims),
        "citation_correctness": metrics.citation_correctness(
            result_payload["sources"],
            expected_filenames=case.get("expected_filenames"),
            expected_pages=case.get("expected_pages"),
        ),
        "hallucination_rate": metrics.hallucination_rate(claims),
        "abstention_correctness": metrics.abstention_correctness(
            case.get("should_abstain", False), result_payload["abstained"]
        ),
    }
    record = {
        "run_id": run_id,
        "case_id": case["id"],
        "category": case["category"],
        "question": question,
        "answer": result_payload["answer"],
        "abstained": result_payload["abstained"],
        "evidence_status": result_payload["evidence_status"],
        "metrics": {key: round(float(value), 4) for key, value in computed.items()},
    }
    db.add(
        EvaluationRecord(
            run_id=run_id,
            user_id=user_id,
            category=case["category"],
            question=question,
            answer=result_payload["answer"][:4000],
            metrics=record["metrics"],
        )
    )
    db.commit()
    return record


async def run_evaluation(user_email: str, output_path: Path) -> Dict:
    dataset = load_dataset()
    run_id = uuid.uuid4().hex[:12]
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == user_email.lower().strip()).first()
        if user is None:
            raise SystemExit(f"No user found with email {user_email}")
        records: List[Dict] = []
        for case in dataset["cases"]:
            logger.info("Evaluating %s", case["id"])
            records.append(await evaluate_case(db, user.id, case, run_id))

    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_email": user_email,
        "dataset_version": dataset.get("version"),
        "overall": metrics.aggregate(records),
        "by_category": metrics.aggregate_by_category(records),
        "records": records,
        "notes": [
            "Metrics are computed offline; they are not production analytics.",
            "Grounding metrics require the configured LLM claim verifier.",
            "Run with external web search disabled for document-grounded evaluation.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["overall"], indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MediQuery RAG evaluation")
    parser.add_argument("--user-email", required=True)
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("reports") / "latest_report.json"),
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_evaluation(args.user_email, Path(args.output)))


if __name__ == "__main__":
    main()
