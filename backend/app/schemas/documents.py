from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_size: int
    upload_date: datetime
    status: str
    progress: int = 0
    stage: Optional[str] = None
    error_message: Optional[str] = None
    rejection_reason: Optional[str] = None
    page_count: int = 0
    chunk_count: int = 0
    mime_type: Optional[str] = None
    is_medical: Optional[int] = None
    domain_confidence: Optional[int] = None


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int


class DocumentStatusResponse(DocumentResponse):
    pass


class DocumentDownloadResponse(BaseModel):
    url: Optional[str] = None
    expires_in: int = 0


class UploadRejection(BaseModel):
    filename: str
    reason: str


class DocumentUploadResponse(BaseModel):
    documents: List[DocumentResponse] = Field(default_factory=list)
    rejected: List[UploadRejection] = Field(default_factory=list)
    message: Optional[str] = None
