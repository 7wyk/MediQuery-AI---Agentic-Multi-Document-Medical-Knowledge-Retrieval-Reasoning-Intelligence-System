"""Trusted medical web search fallback.

Only authoritative biomedical sources are queried.  Europe PMC (which indexes
PubMed/MEDLINE) is used because it is free, requires no API key and returns
structured citation metadata.  Result URLs are constructed on allow-listed
domains and every item is clearly tagged as external evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

from app.config import get_settings
from app.providers.base import ProviderError
from app.providers.http import request_json
from app.schemas.chat import SourceCitation
from app.services.observability import RequestTrace

logger = logging.getLogger(__name__)

EUROPE_PMC_ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


@dataclass
class WebEvidence:
    title: str
    content: str
    url: str
    publisher: str
    year: Optional[str] = None
    identifier: Optional[str] = None

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.lower()

    def as_citation(self, index: int) -> SourceCitation:
        return SourceCitation(
            index=index,
            kind="web",
            title=self.title,
            url=self.url,
            publisher=self.publisher,
            snippet=self.content[:600],
            filename=None,
        )


def _is_trusted(url: str, allowed_domains: List[str]) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


async def search_medical_web(
    question: str,
    *,
    max_results: Optional[int] = None,
    trace: Optional[RequestTrace] = None,
) -> List[WebEvidence]:
    settings = get_settings()
    if not settings.web_search_enabled:
        return []
    if settings.web_search_provider.lower() != "europepmc":
        logger.warning("Unsupported WEB_SEARCH_PROVIDER: %s", settings.web_search_provider)
        return []

    limit = max(1, min(max_results or settings.web_search_max_results, 10))
    try:
        with (trace.stage("web_search") if trace else _nullcontext()):
            payload = await request_json(
                "GET",
                EUROPE_PMC_ENDPOINT,
                provider="europepmc",
                params={
                    "query": question[:500],
                    "format": "json",
                    "pageSize": limit,
                    "resultType": "core",
                    "sort": "CITED desc",
                },
                timeout=settings.web_search_timeout_seconds,
                retries=1,
            )
    except ProviderError as exc:
        logger.warning("Medical web search failed: %s", exc)
        if trace:
            trace.add_error("External medical search was unavailable.")
        return []

    body = payload.get("resultList") or {}
    results = body.get("result") or []
    evidence: List[WebEvidence] = []
    for item in results:
        title = (item.get("title") or "").strip()
        abstract = (item.get("abstractText") or "").strip()
        if not title or not abstract:
            continue
        pmid = item.get("pmid")
        source = item.get("source") or "MED"
        identifier = item.get("id")
        if pmid:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        elif identifier:
            url = f"https://europepmc.org/article/{source}/{identifier}"
        else:
            continue
        if not _is_trusted(url, settings.allowed_web_domains):
            logger.warning("Discarding untrusted web evidence host: %s", url)
            continue
        publisher = (
            item.get("journalInfo", {}).get("journal", {}).get("title")
            or item.get("bookOrReportDetails", {}).get("publisher")
            or "Europe PMC / PubMed"
        )
        year = item.get("pubYear")
        evidence.append(
            WebEvidence(
                title=title,
                content=abstract,
                url=url,
                publisher=str(publisher),
                year=str(year) if year else None,
                identifier=str(pmid or identifier),
            )
        )
        if len(evidence) >= limit:
            break
    return evidence


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *args) -> bool:
        return False
