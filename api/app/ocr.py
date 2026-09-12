"""Local OCR. Tesseract only -- no hosted vision API, no torch.

Two constraints shape this file:

1. 512MB. A PDF page rendered at 300 DPI is ~25MB as an RGB bitmap, and
   Tesseract holds its own copy. So pages are rendered ONE at a time at 200
   DPI, greyscaled, and released before the next one. Rendering the whole
   document up front is what OOMs the container.

2. Privacy. Only the extracted text and parsed grade are persisted -- the
   upload itself is dropped when the request ends. Note the caveat: Starlette
   spools a multipart upload above ~1MB to a temp file, so bytes can briefly
   touch disk during parsing before the OS removes the file. That window is
   bounded by MaxBodySizeMiddleware (app/limits.py), which rejects anything
   over MAX_BYTES before parsing begins.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from .grading import NormalizedGrade, normalize

# Rendering beyond this resolution costs memory without helping Tesseract,
# which is tuned for roughly 300 DPI text but copes well at 200.
RENDER_DPI = 200
MAX_PAGES = 5
MAX_BYTES = 10 * 1024 * 1024
# Tesseract's own ceiling; a transcript wider than this is a scan artefact.
MAX_PIXELS = 4000


@dataclass
class OcrResult:
    text: str
    confidence: float  # 0..100, Tesseract's mean word confidence
    pages: int
    grade: NormalizedGrade | None


def _ocr_image(img: Image.Image) -> tuple[str, list[float]]:
    """OCR one page, returning text and per-word confidences."""
    # Greyscale halves the bitmap and Tesseract binarises internally anyway.
    if img.mode != "L":
        img = img.convert("L")
    if max(img.size) > MAX_PIXELS:
        img.thumbnail((MAX_PIXELS, MAX_PIXELS))

    data = pytesseract.image_to_data(
        img, output_type=pytesseract.Output.DICT, config="--psm 6"
    )
    words, confs = [], []
    for word, conf in zip(data["text"], data["conf"], strict=False):
        if not word.strip():
            continue
        words.append(word)
        try:
            c = float(conf)
        except (TypeError, ValueError):
            continue
        if c >= 0:  # Tesseract uses -1 for "no confidence"
            confs.append(c)
    return " ".join(words), confs


def _pdf_to_text(data: bytes) -> tuple[str, list[float], int]:
    pdf = pdfium.PdfDocument(data)
    try:
        n = min(len(pdf), MAX_PAGES)
        chunks, confs = [], []
        for i in range(n):
            page = pdf[i]
            bitmap = page.render(scale=RENDER_DPI / 72, grayscale=True)
            img = bitmap.to_pil()
            try:
                text, page_confs = _ocr_image(img)
            finally:
                # Explicit teardown: without it the peak of page N and page N+1
                # overlap, which is exactly what blows the memory limit.
                img.close()
                del bitmap
                page.close()
            chunks.append(text)
            confs.extend(page_confs)
        return "\n".join(chunks), confs, n
    finally:
        pdf.close()


def extract(data: bytes, content_type: str, country: str | None = None) -> OcrResult:
    """Run OCR over an upload and pull out the best grade we can find."""
    if len(data) > MAX_BYTES:
        raise ValueError(f"file is larger than {MAX_BYTES // (1024 * 1024)}MB")
    if not data:
        raise ValueError("empty file")

    if "pdf" in content_type.lower():
        text, confs, pages = _pdf_to_text(data)
    else:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            text, confs = _ocr_image(img)
        pages = 1

    confidence = round(sum(confs) / len(confs), 2) if confs else 0.0
    return OcrResult(
        text=text, confidence=confidence, pages=pages, grade=find_grade(text, country)
    )


# Ordered by how much we trust each pattern, best first. The first one that
# normalises with usable confidence wins.
_GRADE_PATTERNS = (
    r"(?:cgpa|gpa|sgpa)\s*[:\-]?\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?",
    r"(?:total|obtained|marks?)\D{0,12}\d{2,4}\s*/\s*\d{3,4}",
    r"\b\d{2,4}\s*/\s*\d{3,4}\b",
    r"\b\d{1,3}(?:[.,]\d+)?\s*%",
    r"\b(?:first\s+class|upper\s+second|lower\s+second|2:1|2:2)\b",
)


def find_grade(text: str, country: str | None = None) -> NormalizedGrade | None:
    """Pick the most credible grade out of OCR text.

    Transcripts contain many numbers -- roll numbers, dates, subject codes. We
    only accept matches that normalise to a real grade, and we return the
    highest-confidence one rather than the first number on the page.
    """
    if not text:
        return None

    best: NormalizedGrade | None = None
    for pattern in _GRADE_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            cand = normalize(m.group(0), country=country)
            if cand.gpa_4 is None:
                continue
            if best is None or cand.confidence > best.confidence:
                best = cand
        # A labelled CGPA/GPA beats anything a looser pattern could find.
        if best is not None and best.confidence >= 0.85:
            break
    return best


def _demo() -> None:
    """Self-check for the text-parsing half (no Tesseract binary needed)."""
    transcript = (
        "BOARD OF INTERMEDIATE EDUCATION  Roll No 123456  Session 2024 "
        "Subject Codes 401 402 403  Total Marks Obtained 920/1100  Grade A+"
    )
    g = find_grade(transcript, country="PK")
    assert g is not None and g.gpa_4 == 4.0, g
    # Must not latch onto the roll number or the session year.
    assert g.percentage is not None and 83 < g.percentage < 84, g

    # A labelled CGPA outranks a stray fraction elsewhere on the page.
    uni = "Semester 3 of 8  CGPA: 3.62  Credits 18/24"
    g2 = find_grade(uni)
    assert g2 is not None and g2.gpa_4 == 3.62, g2

    assert find_grade("no numbers of any kind here") is None
    assert find_grade("") is None
    print("ocr text-parsing self-check passed")


if __name__ == "__main__":
    _demo()
