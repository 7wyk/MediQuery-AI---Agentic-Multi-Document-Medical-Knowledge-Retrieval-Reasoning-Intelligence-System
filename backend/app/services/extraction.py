"""Document extraction for multimodal medical uploads.

Supported inputs: PDF (text and scanned), DOCX, XLSX, CSV, TXT, JPG/JPEG, PNG.
Text, tables, charts and images are extracted into typed blocks that retain
page numbers, section names and table/chart identifiers so retrieval can cite
them accurately.  OCR and image understanding are performed by hosted APIs;
nothing here downloads or runs a local model.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import Settings
from app.providers.base import OCRProvider, ProviderError, VisionProvider

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"pdf", "docx", "xlsx", "csv", "txt", "png", "jpeg"}
MIME_BY_TYPE = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
    "png": "image/png",
    "jpeg": "image/jpeg",
}

_IMAGE_PROMPT = """You are analysing an image extracted from a medical document.
Return ONLY a JSON object with this schema:
{
  "document_type": "chart" | "table" | "medical_image" | "text",
  "title": "short title or empty string",
  "text": "all readable text exactly as printed, preserving headings and rows",
  "chart": {
     "chart_type": "line|bar|pie|scatter|other|none",
     "x_axis": "label and units",
     "y_axis": "label and units",
     "legend": ["series names"],
     "data_points": [{"label": "...", "series": "...", "value": "..."}],
     "trend": "one sentence describing the visible trend"
  }
}
Describe only what is visibly present. Do not invent numbers. Use empty values
when a field is not applicable."""


class ExtractionError(RuntimeError):
    pass


@dataclass
class ExtractedBlock:
    content: str
    content_type: str = "text"
    page: Optional[int] = None
    section: Optional[str] = None
    table_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    blocks: List[ExtractedBlock]
    file_type: str
    page_count: int
    metadata: dict = field(default_factory=dict)

    @property
    def combined_text(self) -> str:
        return "\n\n".join(block.content for block in self.blocks if block.content)


def detect_file_type(data: bytes, filename: str) -> str:
    """Detect the real file type from magic bytes (never trust the extension)."""
    if not data:
        raise ExtractionError("The uploaded file is empty.")
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"PK\x03\x04":
        try:
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError("The uploaded archive is corrupt or unsupported.") from exc
        if any(name.startswith("word/") for name in names):
            return "docx"
        if any(name.startswith("xl/") for name in names):
            return "xlsx"
        raise ExtractionError(
            "ZIP archives other than DOCX/XLSX are not supported medical documents."
        )
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ExtractionError("Legacy binary Office files are not supported; upload DOCX/XLSX.")
    if b"\x00" in data[:2048]:
        raise ExtractionError("The uploaded file is not a recognised document format.")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 decodes anything
            raise ExtractionError("Could not decode the uploaded text file.") from exc

    sample = text[:4000]
    lower_name = (filename or "").lower()
    if lower_name.endswith(".csv"):
        return "csv"
    if sample.count(",") >= max(4, sample.count("\n")) or sample.count("\t") > 5:
        return "csv"
    return "txt"


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _guess_section(text: str) -> Optional[str]:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if 0 < len(first_line) <= 120 and not first_line.endswith("."):
        return first_line
    return None


class DocumentExtractor:
    def __init__(
        self,
        settings: Settings,
        *,
        ocr: Optional[OCRProvider] = None,
        vision: Optional[VisionProvider] = None,
    ) -> None:
        self.settings = settings
        self.ocr = ocr
        self.vision = vision
        self._image_budget = settings.max_image_analysis_per_document
        self._ocr_budget = settings.max_ocr_pages

    # ------------------------------------------------------------------ public
    async def extract(self, data: bytes, file_type: str, filename: str) -> ExtractionResult:
        if file_type not in SUPPORTED_TYPES:
            raise ExtractionError(f"Unsupported file type: {file_type}")
        if file_type == "pdf":
            return await self._extract_pdf(data, filename)
        if file_type == "docx":
            return self._extract_docx(data)
        if file_type == "xlsx":
            return self._extract_xlsx(data)
        if file_type == "csv":
            return self._extract_csv(data)
        if file_type == "txt":
            return self._extract_txt(data)
        return await self._extract_image(data, file_type)

    # --------------------------------------------------------------------- pdf
    async def _extract_pdf(self, data: bytes, filename: str) -> ExtractionResult:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError("The PDF could not be opened or is password protected.") from exc

        page_count = len(reader.pages)
        if page_count == 0:
            raise ExtractionError("The PDF contains no pages.")
        if page_count > self.settings.max_document_pages:
            raise ExtractionError(
                f"The PDF has {page_count} pages; the limit is {self.settings.max_document_pages}."
            )

        blocks: List[ExtractedBlock] = []
        scanned_pages = 0
        images_analysed = 0

        for index, page in enumerate(reader.pages, start=1):
            try:
                text = _clean(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("PDF page %s text extraction failed: %s", index, exc)
                text = ""
            if text:
                blocks.append(ExtractedBlock(content=text, page=index, section=_guess_section(text)))

            if len(text) < 40:
                scanned_pages += 1
                ocr_text = await self._ocr_pdf_page(data, index)
                if ocr_text:
                    blocks.append(
                        ExtractedBlock(
                            content=ocr_text,
                            page=index,
                            section=_guess_section(ocr_text),
                            metadata={"extraction": "ocr"},
                        )
                    )

            if (
                self.settings.enable_image_analysis
                and self.vision is not None
                and images_analysed < self._image_budget
            ):
                analysed = await self._analyse_embedded_images(page, index, images_analysed)
                images_analysed += analysed

        if not blocks:
            raise ExtractionError(
                "No readable text could be extracted. The scan quality may be too low for OCR."
            )

        return ExtractionResult(
            blocks=blocks,
            file_type="pdf",
            page_count=page_count,
            metadata={
                "scanned_pages": scanned_pages,
                "images_analysed": images_analysed,
                "ocr_used": scanned_pages > 0,
                "original_filename": filename,
            },
        )

    async def _ocr_pdf_page(self, data: bytes, page_number: int) -> str:
        if self.ocr is None or not self.ocr.available or self._ocr_budget <= 0:
            return ""
        self._ocr_budget -= 1
        try:
            import pymupdf

            with pymupdf.open(stream=data, filetype="pdf") as document:
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(dpi=170)
                image_bytes = pixmap.tobytes("png")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not rasterise PDF page %s: %s", page_number, exc)
            return ""
        try:
            return _clean(await self.ocr.extract_text(image_bytes, "image/png"))
        except ProviderError as exc:
            logger.warning("OCR provider failed on page %s: %s", page_number, exc)
            return ""

    async def _analyse_embedded_images(self, page, page_number: int, analysed: int) -> int:  # noqa: ANN001
        count = 0
        try:
            images = list(page.images)
        except Exception:  # noqa: BLE001
            return 0
        for image in images:
            if analysed + count >= self._image_budget:
                break
            try:
                payload = image.data
            except Exception:  # noqa: BLE001
                continue
            if not payload or len(payload) < 8000:
                continue
            bundle = await self._describe_image(payload, "image/png", page_number, source="pdf_image")
            if bundle:
                count += 1
        return count

    # ------------------------------------------------------------------- image
    async def _extract_image(self, data: bytes, file_type: str) -> ExtractionResult:
        if self.vision is None and (self.ocr is None or not self.ocr.available):
            raise ExtractionError(
                "Image documents require a configured OCR or vision provider."
            )
        mime = MIME_BY_TYPE[file_type]
        blocks: List[ExtractedBlock] = []
        describe = await self._describe_image(data, mime, 1, source="upload")
        if describe and describe.get("text"):
            blocks.append(
                ExtractedBlock(
                    content=describe["text"],
                    content_type="chart" if describe.get("document_type") == "chart" else "image",
                    page=1,
                    section=describe.get("title") or None,
                    metadata={"extraction": describe.get("provider", "vision"), "image_type": file_type},
                )
            )
        if not blocks and self.ocr is not None and self.ocr.available:
            text = _clean(await self.ocr.extract_text(data, mime))
            if text:
                blocks.append(ExtractedBlock(content=text, content_type="image", page=1))
        if not blocks:
            raise ExtractionError("No readable content was found in the image.")
        return ExtractionResult(
            blocks=blocks,
            file_type=file_type,
            page_count=1,
            metadata={"image_type": file_type},
        )

    async def _describe_image(
        self, image_bytes: bytes, mime: str, page: int, *, source: str
    ) -> Optional[dict]:
        if self.vision is None:
            return None
        try:
            raw = await self.vision.describe_image(image_bytes, mime, _IMAGE_PROMPT)
        except ProviderError as exc:
            logger.warning("Vision analysis failed (%s): %s", source, exc)
            return None
        parsed: dict = {}
        try:
            cleaned = raw.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.lstrip().startswith("json"):
                    cleaned = cleaned.lstrip()[4:]
            parsed = json.loads(cleaned.strip().strip("`"))
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception:  # noqa: BLE001 - fall back to raw text
            parsed = {"document_type": "text", "text": raw}
        text = _clean(str(parsed.get("text") or raw))
        chart = parsed.get("chart") or {}
        if isinstance(chart, dict) and parsed.get("document_type") == "chart":
            details = []
            if chart.get("chart_type"):
                details.append(f"Chart type: {chart['chart_type']}")
            if chart.get("title") or parsed.get("title"):
                details.append(f"Title: {parsed.get('title') or chart.get('title')}")
            if chart.get("x_axis"):
                details.append(f"X axis: {chart['x_axis']}")
            if chart.get("y_axis"):
                details.append(f"Y axis: {chart['y_axis']}")
            if chart.get("legend"):
                details.append(f"Legend: {', '.join(map(str, chart['legend']))}")
            points = chart.get("data_points") or []
            if isinstance(points, list) and points:
                rendered = "; ".join(
                    f"{p.get('label', '')} {p.get('series', '')}: {p.get('value', '')}".strip()
                    for p in points[:40]
                    if isinstance(p, dict)
                )
                if rendered:
                    details.append(f"Data points: {rendered}")
            if chart.get("trend"):
                details.append(f"Trend: {chart['trend']}")
            if details:
                text = (text + "\n\n" if text else "") + "\n".join(details)
        if not text:
            return None
        return {
            "text": text,
            "document_type": parsed.get("document_type") or "text",
            "title": parsed.get("title") or "",
            "provider": self.vision.name,
            "page": page,
        }

    # ------------------------------------------------------------------- docx
    def _extract_docx(self, data: bytes) -> ExtractionResult:
        try:
            import docx

            document = docx.Document(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError("The DOCX file could not be opened.") from exc

        blocks: List[ExtractedBlock] = []
        section: Optional[str] = None
        paragraphs: List[str] = []

        def flush() -> None:
            if paragraphs:
                text = _clean("\n\n".join(paragraphs))
                if text:
                    blocks.append(ExtractedBlock(content=text, page=1, section=section))
                paragraphs.clear()

        for paragraph in document.paragraphs:
            text = _clean(paragraph.text)
            if not text:
                continue
            style = (getattr(paragraph.style, "name", "") or "").lower()
            if style.startswith("heading") or style == "title":
                flush()
                section = text[:200]
                continue
            paragraphs.append(text)
        flush()

        for table_index, table in enumerate(document.tables, start=1):
            rows = []
            for row in table.rows:
                cells = [_clean(cell.text).replace("\n", " ") for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(
                    ExtractedBlock(
                        content="\n".join(rows),
                        content_type="table",
                        page=1,
                        section=section,
                        table_id=f"table-{table_index}",
                    )
                )

        if not blocks:
            raise ExtractionError("The DOCX file contains no extractable text or tables.")
        return ExtractionResult(blocks=blocks, file_type="docx", page_count=1)

    # ------------------------------------------------------------------- xlsx
    def _extract_xlsx(self, data: bytes) -> ExtractionResult:
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError("The XLSX workbook could not be opened.") from exc

        blocks: List[ExtractedBlock] = []
        sheet_count = 0
        for sheet in workbook.worksheets:
            sheet_count += 1
            rows: List[List[str]] = []
            for row in sheet.iter_rows(values_only=True):
                values = ["" if cell is None else str(cell).strip() for cell in row]
                if any(values):
                    rows.append(values)
            if not rows:
                continue
            header = rows[0]
            blocks.append(
                ExtractedBlock(
                    content=(
                        f"Sheet '{sheet.title}' with columns: "
                        + ", ".join(v for v in header if v)
                    ),
                    page=sheet_count,
                    section=sheet.title,
                    metadata={"row_count": len(rows) - 1},
                )
            )
            width = max(len(r) for r in rows)
            normalised = [r + [""] * (width - len(r)) for r in rows]
            header_line = " | ".join(normalised[0])
            group_size = 20
            for start in range(1, len(normalised), group_size):
                group = normalised[start : start + group_size]
                body = "\n".join(" | ".join(cell for cell in r) for r in group)
                content = header_line + "\n" + body
                blocks.append(
                    ExtractedBlock(
                        content=content,
                        content_type="table",
                        page=sheet_count,
                        section=sheet.title,
                        table_id=f"{sheet.title}:rows-{start}-{start + len(group) - 1}",
                        metadata={"header": [h for h in header if h]},
                    )
                )
        if not blocks:
            raise ExtractionError("The workbook contains no data.")
        return ExtractionResult(
            blocks=blocks, file_type="xlsx", page_count=max(1, sheet_count)
        )

    # -------------------------------------------------------------------- csv
    def _extract_csv(self, data: bytes) -> ExtractionResult:
        text = data.decode("utf-8", errors="replace")
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except csv.Error as exc:
            raise ExtractionError("The CSV file could not be parsed.") from exc
        rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            raise ExtractionError("The CSV file contains no rows.")
        header = rows[0]
        blocks = [
            ExtractedBlock(
                content="CSV columns: " + ", ".join(header),
                page=1,
                section="CSV summary",
                metadata={"row_count": len(rows) - 1},
            )
        ]
        group_size = 25
        for start in range(1, len(rows), group_size):
            group = rows[start : start + group_size]
            content = " | ".join(header) + "\n" + "\n".join(" | ".join(r) for r in group)
            blocks.append(
                ExtractedBlock(
                    content=content,
                    content_type="table",
                    page=1,
                    section="CSV rows",
                    table_id=f"csv-rows-{start}-{start + len(group) - 1}",
                )
            )
        return ExtractionResult(blocks=blocks, file_type="csv", page_count=1)

    # -------------------------------------------------------------------- txt
    def _extract_txt(self, data: bytes) -> ExtractionResult:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        cleaned = _clean(text)
        if not cleaned:
            raise ExtractionError("The text file is empty.")
        blocks = [
            ExtractedBlock(content=cleaned, page=1, section=_guess_section(cleaned))
        ]
        return ExtractionResult(blocks=blocks, file_type="txt", page_count=1)
