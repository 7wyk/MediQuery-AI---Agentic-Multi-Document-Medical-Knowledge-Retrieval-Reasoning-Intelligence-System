"""Hosted OCR and vision providers used for scanned documents and charts."""

from __future__ import annotations

import base64
import logging
from typing import Optional

from app.config import Settings
from app.providers.base import OCRProvider, ProviderError, ProviderNotConfigured, VisionProvider
from app.providers.http import request_json

logger = logging.getLogger(__name__)


class GeminiVisionProvider(VisionProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise ProviderNotConfigured("gemini-vision", "GEMINI_API_KEY")
        self.settings = settings
        self.api_key = settings.gemini_api_key
        self.model = settings.vision_model
        self.base_url = settings.gemini_base_url.rstrip("/") + "/v1beta"

    async def describe_image(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type or "image/png",
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1600},
        }
        response = await request_json(
            "POST",
            f"{self.base_url}/models/{self.model}:generateContent",
            provider="gemini-vision",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.settings.ai_request_timeout_seconds,
            retries=self.settings.ai_max_retries,
        )
        candidates = response.get("candidates") or []
        if not candidates:
            raise ProviderError("gemini-vision", "no candidates returned")
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "\n".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise ProviderError("gemini-vision", "empty vision response")
        return text


class NullVisionProvider(VisionProvider):
    name = "none"

    def describe_image(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:  # type: ignore[override]
        raise ProviderNotConfigured("vision", "VISION_PROVIDER")


class GeminiOCRProvider(OCRProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.vision = GeminiVisionProvider(settings)

    @property
    def available(self) -> bool:
        return True

    async def extract_text(self, image_bytes: bytes, mime_type: str) -> str:
        prompt = (
            "Extract every readable character from this medical document image exactly as it "
            "appears. Preserve headings, table rows and numeric values. Output plain text only."
        )
        return await self.vision.describe_image(image_bytes, mime_type, prompt)


class OcrSpaceProvider(OCRProvider):
    """OCR.space free tier (limited by monthly quota and file size)."""

    name = "ocrspace"

    def __init__(self, settings: Settings) -> None:
        if not settings.ocrspace_api_key:
            raise ProviderNotConfigured("ocrspace", "OCRSPACE_API_KEY")
        self.settings = settings
        self.api_key = settings.ocrspace_api_key
        self.base_url = settings.ocrspace_base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return True

    async def extract_text(self, image_bytes: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = await request_json(
            "POST",
            f"{self.base_url}/parse/image",
            provider="ocrspace",
            data={
                "apikey": self.api_key,
                "base64Image": f"data:{mime_type or 'image/png'};base64,{encoded}",
                "language": "eng",
                "isOverlayRequired": "false",
                "scale": "true",
                "OCREngine": "2",
            },
            timeout=self.settings.ai_request_timeout_seconds,
            retries=self.settings.ai_max_retries,
        )
        if payload.get("IsErroredOnProcessing"):
            message = payload.get("ErrorMessage") or ["OCR provider rejected the image"]
            raise ProviderError("ocrspace", str(message)[:300])
        results = payload.get("ParsedResults") or []
        text = "\n".join(item.get("ParsedText", "") for item in results).strip()
        return text


class NullOCRProvider(OCRProvider):
    name = "none"

    @property
    def available(self) -> bool:
        return False

    async def extract_text(self, image_bytes: bytes, mime_type: str) -> str:
        return ""


def build_vision_provider(settings: Settings) -> Optional[VisionProvider]:
    provider = settings.vision_provider.strip().lower()
    if provider in {"none", "off", "disabled"}:
        return None
    if provider == "gemini":
        return GeminiVisionProvider(settings)
    raise ProviderError("vision", f"unsupported VISION_PROVIDER '{provider}'")


def build_ocr_provider(settings: Settings) -> OCRProvider:
    provider = settings.ocr_provider.strip().lower()
    if provider in {"none", "off", "disabled"}:
        return NullOCRProvider()
    if provider == "gemini":
        return GeminiOCRProvider(settings)
    if provider == "ocrspace":
        return OcrSpaceProvider(settings)
    raise ProviderError("ocr", f"unsupported OCR_PROVIDER '{provider}'")
