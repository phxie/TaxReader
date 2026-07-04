"""
Hybrid PDF text extraction: native text extraction with OCR fallback.

Strategy:
1. For each page, try native text extraction (PyMuPDF) — fast and accurate
   for digitally-generated PDFs.
2. If a page's extracted text is too sparse (below a character threshold,
   or mostly whitespace/garbage), treat it as a scanned/image page and
   run OCR on it instead, using either EasyOCR (via Docling) or
   pytesseract, selected per call via the `ocr_engine` argument.
3. Return combined text with per-page metadata about which method was used
   (useful for debugging and for flagging low-confidence pages for review).

Install:
    pip install pymupdf "docling[easyocr]" pytesseract --break-system-packages
    # EasyOCR downloads its recognition models on first use (CPU or GPU),
    # no external binary required.
    # pytesseract requires the Tesseract OCR binary to be installed
    # separately and available on PATH (or set
    # pytesseract.pytesseract.tesseract_cmd to its location).
"""

import fitz  # PyMuPDF
import io
from dataclasses import dataclass
from typing import List, Literal

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, ImageFormatOption

OcrEngine = Literal["easyocr", "pytesseract"]


# Minimum characters of "real" text before we trust native extraction.
# Scanned pages typically extract to 0 chars, but some have stray
# artifacts (headers baked into the file, etc.), so a small buffer
# avoids false positives.
MIN_CHARS_THRESHOLD = 20

# DPI for rendering pages to images before OCR. Higher = better OCR
# accuracy but slower and more memory. 300 is a good default for
# printed documents like tax notices.
OCR_RENDER_DPI = 300

# Cap on the longest side (in pixels) of a page image sent to OCR.
# EasyOCR's perspective-correction step (cv2.warpPerspective) indexes
# coordinates as signed 16-bit ints, so images with a dimension near
# 32767px can crash with an OpenCV assertion error. Oversized PDF pages
# (e.g. poster/banner-sized canvases) are downscaled to this cap before
# OCR instead of always rendering at OCR_RENDER_DPI.
MAX_OCR_DIMENSION = 4000


@dataclass
class PageResult:
    page_number: int
    text: str
    method: str  # "native" or "ocr"
    char_count: int


def extract_native_text(page: fitz.Page) -> str:
    """Extract embedded text directly from the PDF page object."""
    return page.get_text().strip()


# Docling converter dedicated to OCR-ing single rendered page images with
# EasyOCR. Built lazily on first use (not at import time) so that callers
# who only want the pytesseract engine never pay the cost of loading the
# EasyOCR models.
_EASYOCR_CONVERTER: DocumentConverter | None = None


def _get_easyocr_converter() -> DocumentConverter:
    global _EASYOCR_CONVERTER
    if _EASYOCR_CONVERTER is None:
        _EASYOCR_CONVERTER = DocumentConverter(
            allowed_formats=[InputFormat.IMAGE],
            format_options={
                InputFormat.IMAGE: ImageFormatOption(
                    pipeline_options=PdfPipelineOptions(
                        do_ocr=True,
                        do_table_structure=False,
                        ocr_options=EasyOcrOptions(lang=["en"], force_full_page_ocr=True),
                    )
                )
            },
        )
    return _EASYOCR_CONVERTER


def _render_page_image(page: fitz.Page, dpi: int) -> bytes:
    """Render a page to PNG bytes, downscaled to stay under MAX_OCR_DIMENSION."""
    zoom = dpi / 72  # PDF default is 72 DPI

    longest_side = max(page.rect.width, page.rect.height)
    max_zoom = MAX_OCR_DIMENSION / longest_side
    zoom = min(zoom, max_zoom)

    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix)
    return pixmap.tobytes("png")


def _ocr_page_easyocr(page: fitz.Page, dpi: int) -> str:
    """OCR a page via Docling + EasyOCR."""
    img_bytes = _render_page_image(page, dpi)
    stream = DocumentStream(name="page.png", stream=io.BytesIO(img_bytes))
    result = _get_easyocr_converter().convert(stream)

    # traverse_pictures=True is required here: full-page OCR places all
    # recognized text as children of a top-level PictureItem rather than
    # directly in the document body.
    return result.document.export_to_text(traverse_pictures=True).strip()


def _ocr_page_pytesseract(page: fitz.Page, dpi: int) -> str:
    """OCR a page via pytesseract (requires the Tesseract binary on PATH)."""
    import pytesseract
    from PIL import Image

    img_bytes = _render_page_image(page, dpi)
    image = Image.open(io.BytesIO(img_bytes))
    return pytesseract.image_to_string(image).strip()


_OCR_ENGINES = {
    "easyocr": _ocr_page_easyocr,
    "pytesseract": _ocr_page_pytesseract,
}


def ocr_page(page: fitz.Page, dpi: int = OCR_RENDER_DPI, ocr_engine: OcrEngine = "easyocr") -> str:
    """Render a page to an image and run OCR on it using the selected engine."""
    try:
        engine_fn = _OCR_ENGINES[ocr_engine]
    except KeyError:
        raise ValueError(f"Unknown ocr_engine {ocr_engine!r}; expected one of {list(_OCR_ENGINES)}")
    return engine_fn(page, dpi)


def is_text_sufficient(text: str, threshold: int = MIN_CHARS_THRESHOLD) -> bool:
    """Decide whether native extraction produced usable text."""
    # Strip whitespace-only artifacts before counting.
    cleaned = "".join(text.split())
    return len(cleaned) >= threshold


def extract_pdf_hybrid(pdf_path: str, ocr_engine: OcrEngine = "easyocr") -> List[PageResult]:
    """
    Extract text from every page in a PDF, using native extraction
    where possible and falling back to OCR per-page where necessary.
    """
    results: List[PageResult] = []
    doc = fitz.open(pdf_path)

    for page_number in range(len(doc)):
        page = doc[page_number]
        native_text = extract_native_text(page)

        if is_text_sufficient(native_text):
            results.append(PageResult(
                page_number=page_number + 1,
                text=native_text,
                method="native",
                char_count=len(native_text),
            ))
        else:
            ocr_text = ocr_page(page, ocr_engine=ocr_engine)
            results.append(PageResult(
                page_number=page_number + 1,
                text=ocr_text,
                method="ocr",
                char_count=len(ocr_text),
            ))

    doc.close()
    return results


def combine_results(results: List[PageResult]) -> str:
    """Join per-page text into a single document string with page markers."""
    parts = []
    for r in results:
        parts.append(f"--- Page {r.page_number} ({r.method}) ---\n{r.text}")
    return "\n\n".join(parts)




if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hybrid PDF text extraction")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument(
        "--engine",
        choices=["easyocr", "pytesseract"],
        default="easyocr",
        help="OCR engine to use for scanned pages (default: easyocr)",
    )
    args = parser.parse_args()

    page_results = extract_pdf_hybrid(args.pdf_path, ocr_engine=args.engine)

    for r in page_results:
        print(f"Page {r.page_number}: method={r.method}, chars={r.char_count}")

    full_text = combine_results(page_results)
    print("\n\n=== COMBINED TEXT ===\n")
    print(full_text)