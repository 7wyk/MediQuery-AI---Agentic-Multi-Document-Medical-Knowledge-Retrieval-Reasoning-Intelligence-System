"""Supabase Storage-only object storage provider.

The bucket should be private. The service-role key is used only server-side.
Signed URLs should be created only after application-level ownership checks.
"""
from __future__ import annotations

import logging
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import quote

from app.config import Settings, get_settings
from app.providers.http import request_json

logger = logging.getLogger(__name__)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(RuntimeError):
    """Raised when a Supabase Storage operation fails."""


def sanitize_filename(filename: str) -> str:
    name = PurePosixPath(filename or "document").name
    name = _SAFE_NAME.sub("_", name).strip("._") or "document"
    return name[:180]


def build_storage_path(user_id: int, document_id: str, filename: str) -> str:
    """Build an ownership-scoped object key using a server-generated document ID."""
    return f"user-{int(user_id)}/{document_id}/{sanitize_filename(filename)}"


class StorageProvider(ABC):
    name: str = "storage"

    @abstractmethod
    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def download(self, path: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def signed_url(
        self, path: str, expires_in: Optional[int] = None
    ) -> Optional[str]:
        raise NotImplementedError


class SupabaseStorage(StorageProvider):
    """Supabase Storage REST client."""

    name = "supabase"

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise StorageError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required."
            )
        if not settings.supabase_storage_bucket:
            raise StorageError("SUPABASE_STORAGE_BUCKET is required.")

        self.settings = settings
        self.base_url = settings.supabase_url.rstrip("/")
        self.bucket = quote(settings.supabase_storage_bucket, safe="")
        self.key = settings.supabase_service_role_key

    def _object_url(self, path: str) -> str:
        safe_path = quote(path.lstrip("/"), safe="/")
        return f"{self.base_url}/storage/v1/object/{self.bucket}/{safe_path}"

    def _headers(self, content_type: Optional[str] = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.key}",
            "apikey": self.key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        import httpx

        headers = self._headers(content_type)
        headers["x-upsert"] = "true"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._object_url(path), content=data, headers=headers
                )
            if response.status_code >= 400:
                raise StorageError(
                    f"Supabase Storage upload failed ({response.status_code})."
                )
        except httpx.HTTPError as exc:
            raise StorageError(
                f"Supabase Storage upload error: {type(exc).__name__}"
            ) from exc

    async def download(self, path: str) -> bytes:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    self._object_url(path), headers=self._headers()
                )
            if response.status_code == 404:
                raise StorageError("Stored object was not found.")
            if response.status_code >= 400:
                raise StorageError(
                    f"Supabase Storage download failed ({response.status_code})."
                )
            return response.content
        except httpx.HTTPError as exc:
            raise StorageError(
                f"Supabase Storage download error: {type(exc).__name__}"
            ) from exc

    async def delete(self, path: str) -> None:
        try:
            await request_json(
                "DELETE",
                f"{self.base_url}/storage/v1/object/{self.bucket}",
                provider="supabase-storage",
                headers=self._headers("application/json"),
                json={"prefixes": [path.lstrip("/")]},
                timeout=30.0,
                retries=1,
            )
        except Exception as exc:
            # Preserve existing best-effort deletion behaviour, but never log secrets.
            logger.warning(
                "Supabase Storage deletion failed (%s).", type(exc).__name__
            )

    async def signed_url(
        self, path: str, expires_in: Optional[int] = None
    ) -> Optional[str]:
        expires = int(expires_in or self.settings.signed_url_expires_seconds)
        safe_path = quote(path.lstrip("/"), safe="/")
        try:
            payload = await request_json(
                "POST",
                f"{self.base_url}/storage/v1/object/sign/{self.bucket}/{safe_path}",
                provider="supabase-storage",
                headers=self._headers("application/json"),
                json={"expiresIn": expires},
                timeout=30.0,
                retries=1,
            )
        except Exception as exc:
            logger.warning(
                "Supabase Storage signed URL creation failed (%s).",
                type(exc).__name__,
            )
            return None

        signed = payload.get("signedURL") or payload.get("signedUrl")
        if not signed:
            return None
        if signed.startswith("http"):
            return signed
        return f"{self.base_url}/storage/v1{signed}"


def build_storage(settings: Optional[Settings] = None) -> StorageProvider:
    """Construct the only supported storage backend."""
    settings = settings or get_settings()
    if settings.storage_backend != "supabase":
        raise StorageError("Only Supabase Storage is supported.")
    return SupabaseStorage(settings)


_storage: Optional[StorageProvider] = None


def get_storage() -> StorageProvider:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def set_storage(provider: Optional[StorageProvider]) -> None:
    """Test hook for injecting a fake storage provider."""
    global _storage
    _storage = provider


def new_document_id() -> str:
    return str(uuid.uuid4())
