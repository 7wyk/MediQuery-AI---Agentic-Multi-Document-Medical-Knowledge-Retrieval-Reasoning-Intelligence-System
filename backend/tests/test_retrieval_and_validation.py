from __future__ import annotations

import pytest

from app.services.chunking import build_chunks
from app.services.domain_validation import (
    lexical_medical_score,
    validate_document_text,
    validate_query,
)
from app.services.extraction import ExtractedBlock, detect_file_type
from app.services.retrieval import SearchHit, deduplicate, reciprocal_rank_fusion


def _hit(chunk_id: str, score: float = 0.0) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="doc",
        user_id=1,
        filename="f.txt",
        content="content",
        score=score,
    )


def test_rrf_prefers_documents_found_by_both_retrievers():
    vector_hits = [_hit("a"), _hit("b"), _hit("c")]
    keyword_hits = [_hit("c"), _hit("d")]
    fused = reciprocal_rank_fusion([vector_hits, keyword_hits], k=60)
    assert fused[0].chunk_id == "c"
    assert {hit.chunk_id for hit in fused} == {"a", "b", "c", "d"}


def test_deduplicate_preserves_first_occurrence():
    hits = [_hit("a"), _hit("a"), _hit("b")]
    unique = deduplicate(hits)
    assert [hit.chunk_id for hit in unique] == ["a", "b"]


def test_signature_detection_uses_content_not_extension():
    assert detect_file_type(b"%PDF-1.7 fake", "report.txt") == "pdf"
    assert detect_file_type(b"\x89PNG\r\n\x1a\nrest", "x.pdf") == "png"
    assert detect_file_type(b"\xff\xd8\xff\xe0rest", "scan") == "jpeg"
    assert detect_file_type(b"Diabetes symptoms and treatment", "x.pdf") == "txt"
    with pytest.raises(Exception):
        detect_file_type(b"PK\x03\x04nonsense", "archive.docx")
    with pytest.raises(Exception):
        detect_file_type(b"\x00\x01\x02\x03", "binary.bin")


@pytest.mark.asyncio
async def test_medical_document_accepted_and_code_rejected():
    medical = (
        "Hypertension clinical guideline. Blood pressure above 140/90 mmHg indicates "
        "hypertension. Patients with diabetes require monitoring. Treatment includes "
        "diet, exercise and antihypertensive medication. Adverse effects and "
        "contraindications must be reviewed before prescribing. "
        "Clinical diagnosis and management of cardiovascular disease."
    )
    result = await validate_document_text(medical)
    assert result.is_medical is True
    assert result.confidence > 0.5

    code = (
        "def main():\n import os\n class Server:\n  def run(self):\n"
        "   return render(component)\nconst app = express();\nnpm install docker kubernetes\n"
    )
    rejected = await validate_document_text(code)
    assert rejected.is_medical is False
    assert rejected.rejection_message


@pytest.mark.asyncio
async def test_non_medical_query_rejected():
    result = await validate_query("Who won the football world cup in 2018?")
    assert result.is_medical is False

    medical = await validate_query("What are the symptoms of diabetes?")
    assert medical.is_medical is True


def test_medical_lexical_score_separates_domains():
    medical_score, medical_hits, _ = lexical_medical_score(
        "Clinical management of hypertension with medication and blood pressure monitoring"
    )
    code_score, _, junk_hits = lexical_medical_score(
        "function class import const npm docker kubernetes server endpoint"
    )
    assert medical_score > 0.3
    assert medical_hits
    assert code_score == 0
    assert junk_hits


def test_table_chunks_keep_header_rows():
    block = ExtractedBlock(
        content="Drug | Dose | Frequency\n" + "\n".join(
            f"Drug{i} | {i * 10}mg | daily" for i in range(60)
        ),
        content_type="table",
        page=2,
        table_id="table-1",
    )
    drafts = build_chunks([block], chunk_size=300, chunk_overlap=0, max_chunks=100)
    assert len(drafts) > 1
    assert all(draft.content.startswith("Drug | Dose | Frequency") for draft in drafts)
    assert all(draft.content_type == "table" for draft in drafts)
    assert all(draft.page == 2 for draft in drafts)


def test_text_chunks_respect_max_size():
    text = " ".join(["Hypertension treatment guidance for patients."] * 80)
    drafts = build_chunks(
        [ExtractedBlock(content=text, page=1)],
        chunk_size=500,
        chunk_overlap=50,
        max_chunks=200,
    )
    assert len(drafts) > 1
    assert max(len(draft.content) for draft in drafts) <= 700
