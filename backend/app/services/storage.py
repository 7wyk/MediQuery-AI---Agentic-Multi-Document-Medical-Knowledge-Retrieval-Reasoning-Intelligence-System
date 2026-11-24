"""Cloud object storage abstraction (Supabase Storage in production)."""

from __future__ import annotations

import logging
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import Optional

from app.config import Settings, get_settings
from app.providers.http import request_json

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(RuntimeError):
    pass


def sanitize_filename(filename: str) -> str:
    name = PurePosixPath(filename or "document").name
    name = _SAFE_NAME.sub("_", name).strip("._") or "document"
    return name[:180]


def build_storage_path(user_id: int, document_id: str, filename: str) -> str:
    """Predictable, ownership-scoped object key.

    The user id and server-generated document id are both part of the prefix, so
    files can never collide across users and deletion is exact.
    """
    return f"user-{int(user_id)}/{document_id}/{sanitize_filename(filename)}"


class StorageProvider(ABC):
    name: str = "storage"

    @abstractmethod
    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        ...

    @abstractmethod
    async def download(self, path: str) -> bytes:
        ...

    @abstractmethod
    async def delete(self, path: str) -> None:
        ...

    @abstractmethod
    async def signed_url(self, path: str, expires_in: Optional[int] = None) -> Optional[str]:
        ...


class SupabaseStorage(StorageProvider):
    """Supabase Storage REST client using the service-role key.

    The bucket must be private; access is only granted through short-lived
    signed URLs generated server-side after an ownership check.
    """

    name = "supabase"

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise StorageError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for Supabase storage"
            )
        self.settings = settings
        self.base_url = settings.supabase_url.rstrip("/")
        self.bucket = settings.supabase_storage_bucket
        self.key = settings.supabase_service_role_key

    def _headers(self, content_type: Optional[str] = None) -> dict:
        headers = {"Authorization": f"Bearer {self.key}", "apikey": self.key}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        import httpx

        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{path}"
        headers = self._headers(content_type)
        headers["x-upsert"] = "true"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, content=data, headers=headers)
            if response.status_code >= 400:
                raise StorageError(
                    f"Supabase storage upload failed ({response.status_code}): {response.text[:200]}"
                )
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase storage upload error: {type(exc).__name__}") from exc

    async def download(self, path: str) -> bytes:
        import httpx

        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{path}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, headers=self._headers())
            if response.status_code == 404:
                raise StorageError("Stored object not found")
            if response.status_code >= 400:
                raise StorageError(f"Supabase storage download failed ({response.status_code})")
            return response.content
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase storage download error: {type(exc).__name__}") from exc

    async def delete(self, path: str) -> None:
        try:
            await request_json(
                "DELETE",
                f"{self.base_url}/storage/v1/object/{self.bucket}",
                provider="supabase-storage",
                headers=self._headers("application/json"),
                json={"prefixes": [path]},
                timeout=30.0,
                retries=1,
            )
        except Exception as exc:  # noqa: BLE001 - deletion is best effort but logged
            logger.warning("Supabase storage delete failed for %s: %s", path, exc)

    async def signed_url(self, path: str, expires_in: Optional[int] = None) -> Optional[str]:
        expires = int(expires_in or self.settings.signed_url_expires_seconds)
        try:
            payload = await request_json(
                "POST",
                f"{self.base_url}/storage/v1/object/sign/{self.bucket}/{path}",
                provider="supabase-storage",
                headers=self._headers("application/json"),
                json={"expiresIn": expires},
                timeout=30.0,
                retries=1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not create signed URL for %s: %s", path, exc)
            return None
        signed = payload.get("signedURL") or payload.get("signedUrl")
        if not signed:
            return None
        if signed.startswith("http"):
            return signed
        return f"{self.base_url}/storage/v1{signed}"


class LocalStorage(StorageProvider):
    """Development/test only. Never enabled in production (validated on startup)."""

    name = "local"

    def __init__(self, settings: Settings) -> None:
        if settings.is_production:
            raise StorageError("Local storage cannot be used in production")
        self.root = Path(settings.storage_local_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        logger.warning("Using local development storage at %s", self.root)

    def _path(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if not str(target).startswith(str(self.root)):
            raise StorageError("Invalid storage path")
        return target

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    async def download(self, path: str) -> bytes:
        target = self._path(path)
        if not target.exists():
            raise StorageError("Stored object not found")
        return target.read_bytes()

    async def delete(self, path: str) -> None:
        target = self._path(path)
        if target.exists():
            target.unlink()

    async def signed_url(self, path: str, expires_in: Optional[int] = None) -> Optional[str]:
        return None


def build_storage(settings: Optional[Settings] = None) -> StorageProvider:
    settings = settings or get_settings()
    backend = settings.storage_backend.strip().lower()
    if backend == "supabase":
        return SupabaseStorage(settings)
    if backend == "local":
        return LocalStorage(settings)
    raise StorageError(f"Unsupported STORAGE_BACKEND '{backend}'")


_storage: Optional[StorageProvider] = None


def get_storage() -> StorageProvider:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def set_storage(provider: Optional[StorageProvider]) -> None:
    """Test hook to inject a fake storage backend."""
    global _storage
    _storage = provider


def new_document_id() -> str:
    return str(uuid.uuid4())
