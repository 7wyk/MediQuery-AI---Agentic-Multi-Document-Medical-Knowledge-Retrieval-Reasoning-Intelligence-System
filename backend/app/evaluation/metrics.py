"""RAG evaluation metrics (production analytics are kept separate)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "what", "which", "who", "how", "why",
    "when", "where", "does", "did", "can", "could", "should", "would", "about", "into",
    "than", "then", "there", "their", "they", "its", "of", "in", "on", "to", "is", "it",
}


def _keywords(text: str) -> set:
    return {
        token.strip(".,;:()[]").lower()
        for token in (text or "").split()
        if len(token) > 2 and token.lower() not in STOPWORDS
    }


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    relevant_set = set(relevant)
    if not retrieved:
        return 0.0
    return len([item for item in retrieved if item in relevant_set]) / len(retrieved)


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    return len(relevant_set & set(retrieved)) / len(relevant_set)


def context_relevance(retrieved_texts: Sequence[str], expected_keywords: Sequence[str]) -> float:
    """Fraction of expected concepts that appear in retrieved context."""
    if not expected_keywords:
        return 0.0
    if not retrieved_texts:
        return 0.0
    haystack = " ".join(retrieved_texts).lower()
    hits = sum(1 for keyword in expected_keywords if keyword.lower() in haystack)
    return hits / len(expected_keywords)


def answer_relevance(answer: str, expected_keywords: Sequence[str]) -> float:
    if not expected_keywords:
        return 0.0
    answer_lower = (answer or "").lower()
    hits = sum(1 for keyword in expected_keywords if keyword.lower() in answer_lower)
    return hits / len(expected_keywords)


def faithfulness(claims: Sequence[dict]) -> float:
    """Supported claims / total claims from the verifier."""
    if not claims:
        return 0.0
    supported = sum(1 for claim in claims if claim.get("supported"))
    return supported / len(claims)


def hallucination_rate(claims: Sequence[dict]) -> float:
    return 1.0 - faithfulness(claims) if claims else 0.0


def citation_correctness(
    citations: Sequence[dict],
    *,
    expected_filenames: Optional[Sequence[str]] = None,
    expected_pages: Optional[Sequence[int]] = None,
) -> float:
    """Fraction of citations that point at existing, expected evidence."""
    if not citations:
        return 0.0
    expected_files = {name.lower() for name in (expected_filenames or [])}
    expected_page_set = set(expected_pages or [])
    correct = 0
    for citation in citations:
        kind = citation.get("kind", "document")
        if kind == "web":
            if citation.get("url"):
                correct += 1
            continue
        filename = (citation.get("filename") or "").lower()
        page = citation.get("page")
        if expected_files and filename not in expected_files:
            continue
        if expected_page_set and page not in expected_page_set:
            continue
        if not filename:
            continue
        correct += 1
    return correct / len(citations)


def groundedness(citations: Sequence[dict], claims: Sequence[dict]) -> float:
    """Combine claim support with citation presence for a single groundedness score."""
    if not claims:
        return 0.0
    supported = [claim for claim in claims if claim.get("supported")]
    if not supported:
        return 0.0
    cited = sum(1 for claim in supported if claim.get("evidence_indexes") or claim.get("evidence"))
    claim_score = len(supported) / len(claims)
    citation_score = cited / len(supported) if supported else 0.0
    has_sources = 1.0 if citations else 0.0
    return round((claim_score * 0.5 + citation_score * 0.3 + has_sources * 0.2), 4)


def abstention_correctness(should_abstain: bool, did_abstain: bool) -> float:
    return 1.0 if bool(should_abstain) == bool(did_abstain) else 0.0


def aggregate(records: Sequence[Dict]) -> Dict[str, float]:
    """Average every numeric metric across evaluated questions."""
    if not records:
        return {}
    totals: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for record in records:
        for key, value in (record.get("metrics") or {}).items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0.0) + float(value)
                counts[key] = counts.get(key, 0) + 1
    return {key: round(totals[key] / counts[key], 4) for key in totals if counts[key]}


def aggregate_by_category(records: Sequence[Dict]) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, List[Dict]] = {}
    for record in records:
        grouped.setdefault(record.get("category", "uncategorised"), []).append(record)
    return {category: aggregate(items) for category, items in grouped.items()}


def containment_accuracy(answer: str, expected: str) -> float:
    """1.0 when the expected answer text is substantially present, 0.0 otherwise."""
    expected_keywords = _keywords(expected)
    if not expected_keywords:
        return 0.0
    answer_keywords = _keywords(answer)
    if not answer_keywords:
        return 0.0
    return len(expected_keywords & answer_keywords) / len(expected_keywords)
