"""Controlled tool registry with MCP-compatible discovery and invocation.

Every tool has a strict Pydantic input schema, a timeout, and a recorded
execution trace.  Results are always tagged ``external=true`` so they can be
kept separate from uploaded-document evidence.  Only an allow-listed set of
read-only medical sources is registered; the LLM never gets arbitrary access.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.models.analytics import ToolExecution
from app.providers.base import ProviderError
from app.providers.http import request_json

logger = logging.getLogger(__name__)

EUROPE_PMC_ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENFDA_LABEL_ENDPOINT = "https://api.fda.gov/drug/label.json"
ICD10_ENDPOINT = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"


class PubMedSearchInput(BaseModel):
    query: str = Field(..., min_length=3, max_length=300, description="Biomedical search terms")
    max_results: int = Field(default=5, ge=1, le=10)


class DrugLabelInput(BaseModel):
    drug_name: str = Field(..., min_length=2, max_length=120)
    limit: int = Field(default=2, ge=1, le=5)


class ICD10LookupInput(BaseModel):
    terms: str = Field(..., min_length=2, max_length=120)
    max_results: int = Field(default=5, ge=1, le=10)


async def _pubmed_search(payload: PubMedSearchInput) -> Dict[str, Any]:
    data = await request_json(
        "GET",
        EUROPE_PMC_ENDPOINT,
        provider="tool-pubmed",
        params={
            "query": payload.query,
            "format": "json",
            "pageSize": payload.max_results,
            "resultType": "core",
            "sort": "CITED desc",
        },
        timeout=20,
        retries=1,
    )
    results = ((data.get("resultList") or {}).get("result")) or []
    items = []
    for item in results[: payload.max_results]:
        pmid = item.get("pmid")
        identifier = item.get("id")
        source = item.get("source") or "MED"
        url = (
            f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            if pmid
            else f"https://europepmc.org/article/{source}/{identifier}"
        )
        items.append(
            {
                "title": item.get("title"),
                "abstract": (item.get("abstractText") or "")[:1200],
                "journal": (item.get("journalInfo") or {}).get("journal", {}).get("title"),
                "year": item.get("pubYear"),
                "pmid": pmid,
                "url": url,
            }
        )
    return {"query": payload.query, "results": items, "publisher": "Europe PMC / PubMed"}


async def _drug_label_lookup(payload: DrugLabelInput) -> Dict[str, Any]:
    safe_name = payload.drug_name.replace('"', " ").strip()
    search = f'openfda.brand_name:"{safe_name}" OR openfda.generic_name:"{safe_name}"'
    data = await request_json(
        "GET",
        OPENFDA_LABEL_ENDPOINT,
        provider="tool-openfda",
        params={"search": search, "limit": payload.limit},
        timeout=20,
        retries=1,
    )
    items = []
    for result in (data.get("results") or [])[: payload.limit]:
        openfda = result.get("openfda") or {}
        items.append(
            {
                "brand_name": (openfda.get("brand_name") or [None])[0],
                "generic_name": (openfda.get("generic_name") or [None])[0],
                "manufacturer": (openfda.get("manufacturer_name") or [None])[0],
                "indications": (result.get("indications_and_usage") or [""])[0][:1200],
                "dosage": (result.get("dosage_and_administration") or [""])[0][:1200],
                "warnings": (result.get("warnings") or [""])[0][:1200],
                "adverse_reactions": (result.get("adverse_reactions") or [""])[0][:1000],
            }
        )
    return {
        "drug": payload.drug_name,
        "results": items,
        "publisher": "openFDA (U.S. Food and Drug Administration)",
        "url": "https://open.fda.gov/apis/drug/label/",
    }


async def _icd10_lookup(payload: ICD10LookupInput) -> Dict[str, Any]:
    data = await request_json(
        "GET",
        ICD10_ENDPOINT,
        provider="tool-icd10",
        params={"terms": payload.terms, "maxList": payload.max_results, "sf": "code,name"},
        timeout=20,
        retries=1,
    )
    codes = data[1] if isinstance(data, list) and len(data) > 1 else []
    display = data[3] if isinstance(data, list) and len(data) > 3 else []
    items = []
    for index, code in enumerate(codes or []):
        name = display[index][1] if index < len(display) and len(display[index]) > 1 else ""
        items.append({"code": code, "name": name})
    return {
        "terms": payload.terms,
        "results": items,
        "publisher": "NLM Clinical Tables (ICD-10-CM)",
        "url": "https://clinicaltables.nlm.nih.gov/",
    }


@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: Type[BaseModel]
    handler: Callable[[Any], Awaitable[Dict[str, Any]]]
    timeout_seconds: float = 20.0
    sensitive: bool = False
    external: bool = True

    def manifest(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_model.model_json_schema(),
            "annotations": {"external": self.external, "sensitive": self.sensitive},
        }


TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "pubmed_search": ToolSpec(
        name="pubmed_search",
        description="Search PubMed/Europe PMC for peer-reviewed biomedical literature.",
        input_model=PubMedSearchInput,
        handler=_pubmed_search,
    ),
    "fda_drug_label": ToolSpec(
        name="fda_drug_label",
        description="Look up official U.S. FDA drug label information (indications, dosage, warnings).",
        input_model=DrugLabelInput,
        handler=_drug_label_lookup,
    ),
    "icd10_lookup": ToolSpec(
        name="icd10_lookup",
        description="Resolve ICD-10-CM diagnosis codes and descriptions.",
        input_model=ICD10LookupInput,
        handler=_icd10_lookup,
    ),
}


def list_tools() -> List[Dict[str, Any]]:
    return [spec.manifest() for spec in TOOL_REGISTRY.values()]


def _record_execution(
    db: Optional[Session],
    *,
    user_id: Optional[int],
    request_id: Optional[str],
    tool_name: str,
    status: str,
    latency_ms: int,
    input_summary: dict,
    output_summary: Optional[dict],
    error: Optional[str],
) -> None:
    if db is None or user_id is None:
        return
    try:
        db.add(
            ToolExecution(
                request_id=request_id,
                user_id=user_id,
                tool_name=tool_name,
                status=status,
                latency_ms=latency_ms,
                input_summary=input_summary,
                output_summary=output_summary,
                error=error,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - tracing must not break the request
        logger.warning("Could not persist tool trace: %s", exc)
        db.rollback()


async def execute_tool(
    *,
    name: str,
    arguments: dict,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
    user_authorized: bool = False,
) -> Dict[str, Any]:
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {"ok": False, "error": f"Unknown tool '{name}'", "external": True}

    if spec.sensitive and not user_authorized:
        return {
            "ok": False,
            "error": "This tool requires explicit user authorization.",
            "external": True,
        }

    started = time.perf_counter()
    try:
        validated = spec.input_model(**arguments)
    except ValidationError as exc:
        return {
            "ok": False,
            "error": "Invalid tool input.",
            "details": exc.errors(include_url=False)[:5],
            "external": True,
        }

    try:
        result = await asyncio.wait_for(spec.handler(validated), timeout=spec.timeout_seconds)
        latency = int((time.perf_counter() - started) * 1000)
        _record_execution(
            db,
            user_id=user_id,
            request_id=request_id,
            tool_name=name,
            status="success",
            latency_ms=latency,
            input_summary=validated.model_dump(),
            output_summary={"result_count": len(result.get("results") or [])},
            error=None,
        )
        return {"ok": True, "tool": name, "external": True, "latency_ms": latency, **result}
    except asyncio.TimeoutError:
        latency = int((time.perf_counter() - started) * 1000)
        _record_execution(
            db,
            user_id=user_id,
            request_id=request_id,
            tool_name=name,
            status="timeout",
            latency_ms=latency,
            input_summary={"arguments": arguments},
            output_summary=None,
            error="timeout",
        )
        return {"ok": False, "error": "The external tool timed out.", "external": True}
    except ProviderError as exc:
        latency = int((time.perf_counter() - started) * 1000)
        logger.warning("Tool %s failed: %s", name, exc)
        _record_execution(
            db,
            user_id=user_id,
            request_id=request_id,
            tool_name=name,
            status="error",
            latency_ms=latency,
            input_summary={"arguments": arguments},
            output_summary=None,
            error=str(exc)[:400],
        )
        return {
            "ok": False,
            "error": "The external medical source is currently unavailable.",
            "external": True,
        }


async def handle_mcp_request(
    payload: dict,
    *,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Minimal MCP-style JSON-RPC dispatch (initialize/list/call)."""
    method = payload.get("method")
    request_token = payload.get("id")
    if method == "initialize":
        result: Any = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "mediquery-medical-tools", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }
    elif method in {"tools/list", "tools.list"}:
        result = {"tools": list_tools()}
    elif method in {"tools/call", "tools.call"}:
        params = payload.get("params") or {}
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        result = await execute_tool(
            name=tool_name,
            arguments=arguments,
            db=db,
            user_id=user_id,
            request_id=request_id,
            user_authorized=False,
        )
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_token,
            "error": {"code": -32601, "message": f"Unsupported method: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_token, "result": result}
