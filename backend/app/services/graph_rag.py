"""Medical knowledge graph extraction, storage and multi-hop retrieval.

Graph RAG supplements document retrieval: it links entities extracted from the
user's own documents and supplies extra evidence, it never replaces the
document-grounded pipeline and never becomes an independent source of facts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.graph import KnowledgeEntity, KnowledgeRelation
from app.providers.base import ProviderError
from app.providers.llm import parse_json_object
from app.providers.registry import get_llm_provider
from app.services.retrieval import SearchHit

logger = logging.getLogger(__name__)

ENTITY_TYPES = {
    "disease", "symptom", "drug", "treatment", "test", "anatomy", "finding",
    "organism", "procedure", "condition",
}

_EXTRACTION_PROMPT = """Extract medical knowledge-graph data from the document excerpt.

Allowed entity types: disease, symptom, drug, treatment, test, anatomy, finding,
organism, procedure, condition.

Return ONLY JSON:
{
  "entities": [{"name": "exact term", "type": "disease", "description": "<=20 words"}],
  "relations": [{"source": "entity name", "target": "entity name",
                 "relation": "treats|causes|is_symptom_of|diagnosed_by|affects|interacts_with|contraindicated_for|monitored_by|complicates|associated_with|part_of|requires",
                 "evidence": "short supporting phrase"}]
}
Only extract facts explicitly stated in the excerpt. Do not invent entities or relations.
Maximum 30 entities and 40 relations."""

_NORMALIZE_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_entity_name(name: str) -> str:
    cleaned = _NORMALIZE_RE.sub(" ", (name or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()[:300]


@dataclass
class GraphContext:
    used: bool = False
    entity_names: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)
    extra_terms: List[str] = field(default_factory=list)


def delete_document_graph(db: Session, document_id: str) -> None:
    relation_ids = [
        row[0]
        for row in db.query(KnowledgeRelation.id)
        .filter(KnowledgeRelation.document_id == document_id)
        .all()
    ]
    if relation_ids:
        db.query(KnowledgeRelation).filter(KnowledgeRelation.id.in_(relation_ids)).delete(
            synchronize_session=False
        )
    db.query(KnowledgeEntity).filter(KnowledgeEntity.document_id == document_id).delete(
        synchronize_session=False
    )
    db.flush()


async def extract_and_store_graph(
    db: Session,
    *,
    user_id: int,
    document_id: str,
    text: str,
    page: Optional[int] = None,
) -> Dict[str, int]:
    """Best-effort extraction; failures never block ingestion."""
    settings = get_settings()
    if not settings.enable_graph_rag or not text.strip():
        return {"entities": 0, "relations": 0}

    try:
        provider = get_llm_provider()
        result = await provider.complete(
            [
                {"role": "system", "content": "You extract structured medical facts as JSON."},
                {"role": "user", "content": _EXTRACTION_PROMPT + "\n\nExcerpt:\n" + text[:12000]},
            ],
            temperature=0.0,
            max_tokens=1400,
            json_mode=True,
        )
        payload = parse_json_object(result.text)
    except (ProviderError, ValueError) as exc:
        logger.warning("Graph extraction skipped for %s: %s", document_id, exc)
        return {"entities": 0, "relations": 0}

    raw_entities = payload.get("entities") or []
    raw_relations = payload.get("relations") or []
    if not isinstance(raw_entities, list):
        raw_entities = []

    by_name: Dict[str, KnowledgeEntity] = {}
    created = 0
    for item in raw_entities[:30]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:300]
        entity_type = str(item.get("type") or "finding").strip().lower()
        if not name or entity_type not in ENTITY_TYPES:
            continue
        normalized = normalize_entity_name(name)
        if not normalized:
            continue
        entity = (
            db.query(KnowledgeEntity)
            .filter(
                KnowledgeEntity.user_id == user_id,
                KnowledgeEntity.normalized_name == normalized,
                KnowledgeEntity.entity_type == entity_type,
            )
            .first()
        )
        if entity is None:
            entity = KnowledgeEntity(
                user_id=user_id,
                name=name,
                normalized_name=normalized,
                entity_type=entity_type,
                description=str(item.get("description") or "")[:500] or None,
                document_id=document_id,
                page=page,
            )
            db.add(entity)
            db.flush()
            created += 1
        by_name[normalized] = entity
        by_name[name.lower()] = entity

    relations_created = 0
    for item in raw_relations[:40]:
        if not isinstance(item, dict):
            continue
        source = by_name.get(normalize_entity_name(str(item.get("source") or "")))
        target = by_name.get(normalize_entity_name(str(item.get("target") or "")))
        relation_type = str(item.get("relation") or "").strip()[:80]
        if not source or not target or not relation_type or source.id == target.id:
            continue
        db.add(
            KnowledgeRelation(
                user_id=user_id,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relation_type=relation_type,
                confidence=0.6,
                document_id=document_id,
                page=page,
                evidence_text=str(item.get("evidence") or "")[:500] or None,
            )
        )
        relations_created += 1

    db.commit()
    logger.info(
        "Graph extraction document=%s entities=%s relations=%s",
        document_id,
        created,
        relations_created,
    )
    return {"entities": created, "relations": relations_created}


def retrieve_graph_context(db: Session, user_id: int, question: str) -> GraphContext:
    settings = get_settings()
    if not settings.enable_graph_rag:
        return GraphContext()
    question_lower = (question or "").lower()
    if len(question_lower) < 3:
        return GraphContext()

    entities = (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.user_id == user_id)
        .limit(600)
        .all()
    )
    if not entities:
        return GraphContext()

    matched = [
        entity
        for entity in entities
        if len(entity.normalized_name) >= 3 and entity.normalized_name in question_lower
    ]
    if not matched:
        # Fall back to meaningful shared words (e.g. "metformin" vs "metformin therapy").
        question_tokens = set(re.findall(r"[a-z]{4,}", question_lower))
        matched = [
            entity
            for entity in entities
            if set(entity.normalized_name.split()) & question_tokens
        ][: settings.graph_max_entities]
    if not matched:
        return GraphContext()

    entity_by_id = {entity.id: entity for entity in entities}
    visited = {entity.id for entity in matched}
    frontier = set(visited)
    facts: List[str] = []

    for _hop in range(max(1, settings.graph_max_hops)):
        if not frontier:
            break
        relations = (
            db.query(KnowledgeRelation)
            .filter(
                KnowledgeRelation.user_id == user_id,
                or_(
                    KnowledgeRelation.source_entity_id.in_(frontier),
                    KnowledgeRelation.target_entity_id.in_(frontier),
                ),
            )
            .limit(120)
            .all()
        )
        next_frontier: set = set()
        for relation in relations:
            source = entity_by_id.get(relation.source_entity_id)
            target = entity_by_id.get(relation.target_entity_id)
            if not source or not target:
                continue
            fact = f"{source.name} ({source.entity_type}) --{relation.relation_type}--> {target.name} ({target.entity_type})"
            if fact not in facts:
                facts.append(fact)
            for entity_id in (relation.source_entity_id, relation.target_entity_id):
                if entity_id not in visited:
                    visited.add(entity_id)
                    next_frontier.add(entity_id)
        frontier = next_frontier
        if len(facts) >= 40:
            break

    names = [
        entity_by_id[entity_id].name
        for entity_id in visited
        if entity_id in entity_by_id
    ]
    return GraphContext(
        used=bool(facts),
        entity_names=names[: settings.graph_max_entities],
        facts=facts[:40],
        extra_terms=names[:10],
    )


def graph_evidence_hits(
    db: Session,
    user_id: int,
    entity_names: Sequence[str],
    *,
    limit: int = 8,
) -> List[SearchHit]:
    """Fetch document chunks mentioning related entities (multi-hop evidence)."""
    names = [name for name in entity_names if len(name) >= 3][:8]
    if not names or not get_settings().enable_graph_rag:
        return []
    conditions = [DocumentChunk.content.ilike(f"%{name}%") for name in names]
    rows = (
        db.query(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(DocumentChunk.user_id == user_id, or_(*conditions))
        .limit(limit)
        .all()
    )
    hits: List[SearchHit] = []
    for chunk, document in rows:
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                user_id=chunk.user_id,
                filename=document.filename,
                content=chunk.content,
                content_type=chunk.content_type,
                page=chunk.page,
                section=chunk.section,
                table_id=chunk.table_id,
                score=0.35,
                metadata={**(chunk.chunk_metadata or {}), "source": "knowledge_graph"},
            )
        )
    return hits
