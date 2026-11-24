"""Medical-domain gatekeeper for uploads and queries.

Strategy (cheap first):
1. Structural/file checks happen before this module runs.
2. A curated medical/clinical lexicon gives a deterministic confidence score.
3. Clear positives are accepted and clear negatives rejected without an LLM.
4. Borderline content is escalated to a hosted LLM classifier that must return
   structured JSON.  Keyword matching alone is never the final word for
   borderline uploads.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional

from app.config import Settings, get_settings
from app.providers.base import ProviderError
from app.providers.llm import parse_json_object
from app.providers.registry import get_llm_provider

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z][a-z0-9\-]{2,}", re.IGNORECASE)

MEDICAL_TERMS = {
    # conditions / specialties
    "disease", "syndrome", "diagnosis", "diagnostic", "pathology", "pathological", "disorder",
    "infection", "inflammatory", "chronic", "acute", "symptom", "symptoms", "etiology",
    "comorbidity", "comorbidities", "prognosis", "complication", "complications", "lesion",
    "malignancy", "carcinoma", "tumor", "tumour", "neoplasm", "metastasis", "benign",
    "diabetes", "hypertension", "hypotension", "asthma", "copd", "pneumonia", "sepsis",
    "stroke", "ischemia", "infarction", "arrhythmia", "atrial", "fibrillation", "angina",
    "atherosclerosis", "hyperlipidemia", "obesity", "anemia", "thrombosis", "embolism",
    "hepatitis", "cirrhosis", "pancreatitis", "colitis", "ulcer", "gastroesophageal",
    "renal", "nephropathy", "dialysis", "hypothyroidism", "hyperthyroidism", "thyroid",
    "osteoporosis", "arthritis", "lupus", "psoriasis", "eczema", "dermatitis", "epilepsy",
    "migraine", "dementia", "alzheimer", "parkinson", "depression", "anxiety", "psychosis",
    "schizophrenia", "bipolar", "ptsd", "adhd", "autism", "covid", "influenza", "tuberculosis",
    "hiv", "hepatitis", "malaria", "dengue", "measles", "meningitis", "encephalitis",
    "glaucoma", "cataract", "retinopathy", "otitis", "sinusitis", "rhinitis", "allergy",
    "anaphylaxis", "fracture", "sprain", "wound", "burn", "trauma", "hemorrhage",
    # anatomy / physiology
    "anatomy", "physiology", "cardiac", "cardiovascular", "pulmonary", "respiratory",
    "gastrointestinal", "hepatic", "neurological", "neurology", "endocrine", "metabolic",
    "immunological", "immunity", "hematologic", "musculoskeletal", "skeletal", "dermatology",
    "pediatric", "pediatrics", "geriatric", "obstetric", "gynecology", "obstetrics",
    "patient", "patients", "clinical", "clinician", "physician", "nurse", "hospital",
    "ward", "intensive", "emergency", "surgery", "surgical", "procedure", "therapy",
    "medication", "medications", "drug", "drugs", "dose", "dosage", "mg", "ml", "mcg",
    "prescription", "contraindication", "contraindications", "adverse", "side", "effects",
    "pharmacokinetics", "pharmacology", "antibiotic", "antibiotics", "analgesic", "insulin",
    "vaccine", "vaccination", "immunization", "screening", "triage", "vital", "vitals",
    "blood", "serum", "plasma", "urine", "glucose", "hba1c", "cholesterol", "creatinine",
    "hemoglobin", "platelet", "leukocyte", "systolic", "diastolic", "bpm", "mmhg",
    "ecg", "ekg", "mri", "ct", "ultrasound", "radiograph", "radiology", "biopsy",
    "histology", "culture", "assay", "biomarker", "guideline", "guidelines", "protocol",
    "treatment", "treatments", "management", "prevention", "mortality", "morbidity",
    "incidence", "prevalence", "epidemiology", "randomized", "placebo", "cohort",
    "systematic", "meta-analysis", "pubmed", "who", "cdc", "nih", "icd",
    "medical", "medicine", "healthcare", "health", "wellness", "nutrition", "dietary",
    "pregnancy", "prenatal", "postpartum", "neonatal", "infant", "adult", "elderly",
    "rehabilitation", "physiotherapy", "psychotherapy", "counseling", "palliative",
    "hospice", "oncology", "cardiology", "pulmonology", "gastroenterology", "nephrology",
    "endocrinology", "immunology", "hematology", "rheumatology", "urology", "orthopedics",
    "anesthesia", "anesthetic", "sedation", "ventilation", "intubation", "catheter",
    "stethoscope", "syringe", "infusion", "transfusion", "transplant", "dialysis",
}

NON_MEDICAL_TERMS = {
    # programming / IT
    "function", "variable", "class", "import", "return", "const", "let", "def", "python",
    "javascript", "typescript", "react", "node", "npm", "docker", "kubernetes", "git",
    "repository", "compile", "compiler", "syntax", "runtime", "algorithm", "database",
    "server", "endpoint", "api", "json", "html", "css", "sql", "query", "fragment",
    "component", "props", "hook", "async", "await", "null", "boolean", "array", "stack",
    "backend", "frontend", "deployment", "container", "linux", "windows", "kernel",
    # legal
    "agreement", "hereby", "jurisdiction", "plaintiff", "defendant", "attorney",
    "court", "statute", "liability", "indemnity", "warranty", "lessee", "lessor",
    # finance / business
    "invoice", "revenue", "profit", "equity", "balance", "ledger", "payroll", "tax",
    "shareholder", "dividend", "marketing", "campaign", "budget", "quarterly",
    # general academia unrelated to medicine
    "literature", "poetry", "novel", "history", "philosophy", "geography", "physics",
    "chemistry", "mathematics", "calculus", "algebra", "astronomy", "football",
}

CODING_PATTERNS = re.compile(
    r"(=>|;\s*$|\bpublic\s+static\b|\bdef\s+\w+\(|\bfunction\s+\w+\(|</?[a-z]+>|\{\s*\n)",
    re.MULTILINE,
)

ALLOWED_FILE_TYPES_TEXT = "PDF, DOCX, XLSX, CSV, TXT, JPG, JPEG or PNG"


@dataclass
class DomainValidationResult:
    is_medical: bool
    confidence: float
    reason: str
    method: str = "heuristic"
    categories: Optional[list] = None

    @property
    def rejection_message(self) -> str:
        return (
            "This document does not appear to be a medical document, so it was not indexed. "
            f"{self.reason} MediQuery AI only accepts medical and clinical material "
            f"({ALLOWED_FILE_TYPES_TEXT})."
        )


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(text)]


def _lexical_profile(text: str) -> tuple[set, set]:
    tokens = _tokenize(text)
    medical_hits = {token for token in tokens if token in MEDICAL_TERMS}
    junk_hits = {token for token in tokens if token in NON_MEDICAL_TERMS}
    return medical_hits, junk_hits


def lexical_medical_score(text: str) -> tuple[float, set, set]:
    """Deterministic 0..1 confidence from the curated lexicon."""
    medical_hits, junk_hits = _lexical_profile(text)
    medical_strength = min(1.0, len(medical_hits) / 12)
    junk_strength = min(1.0, len(junk_hits) / 8)
    coding_penalty = 0.35 if CODING_PATTERNS.search(text[:6000]) else 0.0
    score = medical_strength * (1 - 0.75 * junk_strength) - coding_penalty
    return max(0.0, min(1.0, score)), medical_hits, junk_hits


_DOC_CLASSIFIER_PROMPT = """You are a strict gatekeeper for a medical RAG system used by
medical professionals. Decide whether the DOCUMENT EXCERPT is medical/clinical material
(clinical guidelines, research, drug information, anatomy, public health, nursing,
medical education) or non-medical (software/programming, legal, finance, marketing,
general fiction, unrelated school subjects).

Borderline medical-adjacent content (nutrition, biology, health policy) may be accepted
when its purpose is clinical or health-related.

Respond ONLY with JSON:
{"is_medical": true|false, "confidence": 0.0-1.0, "reason": "one short sentence", "categories": ["..."]}"""

_QUERY_CLASSIFIER_PROMPT = """Decide whether the USER QUESTION is a medical/clinical/health
question suitable for a medical document assistant. Programming, legal, financial, general
knowledge and chit-chat questions are not medical.

Respond ONLY with JSON:
{"is_medical": true|false, "confidence": 0.0-1.0, "reason": "one short sentence"}"""


async def _llm_classify(text: str, *, kind: str) -> Optional[dict]:
    settings = get_settings()
    if not settings.medical_domain_llm_check:
        return None
    try:
        provider = get_llm_provider()
    except ProviderError as exc:
        logger.warning("Domain LLM check unavailable: %s", exc)
        return None
    system = _DOC_CLASSIFIER_PROMPT if kind == "document" else _QUERY_CLASSIFIER_PROMPT
    try:
        result = await provider.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text[:6000]},
            ],
            temperature=0.0,
            max_tokens=220,
            json_mode=True,
        )
        parsed = parse_json_object(result.text)
    except (ProviderError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Domain LLM classification failed: %s", exc)
        return None
    if "is_medical" not in parsed:
        return None
    return {
        "is_medical": bool(parsed.get("is_medical")),
        "confidence": float(parsed.get("confidence") or 0.5),
        "reason": str(parsed.get("reason") or "").strip()[:300],
        "categories": parsed.get("categories") or [],
    }


async def validate_document_text(
    text: str, *, settings: Optional[Settings] = None
) -> DomainValidationResult:
    settings = settings or get_settings()
    cleaned = (text or "").strip()
    if len(cleaned) < 120:
        return DomainValidationResult(
            is_medical=False,
            confidence=0.95,
            reason="The document contains too little readable text to be a medical document.",
            method="structure",
        )

    score, medical_hits, junk_hits = lexical_medical_score(cleaned)
    threshold = settings.medical_domain_threshold

    if score >= 0.55 and len(medical_hits) >= 6:
        return DomainValidationResult(
            is_medical=True,
            confidence=min(0.99, 0.6 + score * 0.4),
            reason="Clinical terminology detected.",
            method="lexical",
            categories=sorted(medical_hits)[:10],
        )
    if score <= 0.05 and len(junk_hits) >= 5:
        return DomainValidationResult(
            is_medical=False,
            confidence=min(0.99, 0.6 + len(junk_hits) / 20),
            reason="The content looks like non-medical material.",
            method="lexical",
            categories=sorted(junk_hits)[:10],
        )

    llm_result = await _llm_classify(cleaned, kind="document")
    if llm_result is not None:
        return DomainValidationResult(
            is_medical=bool(llm_result["is_medical"]),
            confidence=float(llm_result["confidence"]),
            reason=llm_result["reason"] or "Classification by hosted model.",
            method="llm",
            categories=llm_result.get("categories") or sorted(medical_hits)[:10],
        )

    # No hosted classifier available: accept only when there is real medical signal.
    is_medical = score >= threshold or len(medical_hits) >= 4
    return DomainValidationResult(
        is_medical=is_medical,
        confidence=round(max(score, 0.4 if is_medical else 0.6), 3),
        reason=(
            "Clinical terminology detected (automatic check; LLM verification unavailable)."
            if is_medical
            else "Insufficient medical terminology to verify this as a medical document."
        ),
        method="lexical-fallback",
        categories=sorted(medical_hits)[:10],
    )


@lru_cache(maxsize=512)
def _cached_query_decision(question: str, threshold: float) -> tuple[bool, float, str, str]:
    score, medical_hits, junk_hits = lexical_medical_score(question)
    if medical_hits and score >= 0.12:
        return True, min(0.99, 0.55 + score), "Clinical terminology detected.", "lexical"
    if junk_hits and not medical_hits:
        return False, 0.9, "The question is not about medicine or health.", "lexical"
    if CODING_PATTERNS.search(question):
        return False, 0.85, "The question appears to be about programming.", "lexical"
    return False, 0.0, "", "undecided"


async def validate_query(question: str) -> DomainValidationResult:
    question = (question or "").strip()
    settings = get_settings()
    if len(question) < 3:
        return DomainValidationResult(False, 0.99, "Please ask a complete medical question.", "structure")

    decided, confidence, reason, method = _cached_query_decision(
        question, settings.medical_domain_threshold
    )
    if method != "undecided":
        return DomainValidationResult(decided, confidence, reason, method)

    llm_result = await _llm_classify(question, kind="query")
    if llm_result is not None:
        result = DomainValidationResult(
            is_medical=bool(llm_result["is_medical"]),
            confidence=float(llm_result["confidence"]),
            reason=llm_result["reason"] or "Classification by hosted model.",
            method="llm",
        )
    else:
        # No signal at all and no classifier: do not silently answer unrelated questions.
        result = DomainValidationResult(
            is_medical=False,
            confidence=0.6,
            reason=(
                "This question doesn't look medical, and the domain classifier is not "
                "configured on this deployment."
            ),
            method="lexical-fallback",
        )

    if not result.is_medical:
        result.reason = result.reason or "This question is outside the medical domain."
    return result


def friendly_query_rejection(result: DomainValidationResult) -> str:
    return (
        "I can only answer questions about medicine, health and the medical documents you "
        "upload. " + (result.reason or "This question appears to be outside that domain.")
    )
