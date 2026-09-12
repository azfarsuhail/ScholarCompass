from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..db import get_db
from ..models import AnonSession, Document
from ..ocr import MAX_BYTES, extract
from ..profile_extract import extract_profile
from ..session import current_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/documents", tags=["documents"])

ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/tiff"}


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    kind: str = "transcript",
    country: str | None = None,
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """OCR a transcript and fold the result into the session profile.

    The upload is not persisted: it is converted to text and dropped when this
    handler returns. The size ceiling is enforced by MaxBodySizeMiddleware
    *before* the body is parsed -- see app/limits.py for why a check in here
    would be too late to prevent either an OOM or a spill to disk.
    """
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            415, f"Unsupported file type '{content_type or 'unknown'}'. "
                 "Upload a PDF or an image of your transcript.")

    data = await file.read()
    # Belt-and-braces: the middleware already rejected anything larger, but a
    # handler that trusts an upstream guard it cannot see is a handler that
    # breaks quietly when someone reorders the middleware stack.
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_BYTES // (1024 * 1024)}MB.")

    # Tesseract is blocking and CPU-bound; running it inline would stall every
    # other request on this single-worker container for the whole OCR pass.
    try:
        result = await run_in_threadpool(extract, data, content_type, country)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001 - a corrupt scan must not 500 the app
        raise HTTPException(422, "Could not read that file. Try a clearer scan.") from e
    finally:
        del data

    grade = result.grade

    # A CV carries far more than a grade -- institution, degree level, field,
    # skills, roles. Extracting it is what turns a six-field form into one the
    # student only has to CHECK. Failure is non-fatal: the grade path still
    # works and the form simply stays empty.
    extracted = None
    if kind in ("resume", "cv"):
        try:
            extracted = await extract_profile(result.text, country)
        except Exception as e:  # noqa: BLE001 - never fail an upload over enrichment
            log.warning("profile extraction failed: %s", e)

    doc = Document(
        session_id=session.id,
        kind=kind,
        filename=file.filename,
        ocr_text=result.text[:20000],
        ocr_confidence=result.confidence,
        normalized={**(grade.as_dict() if grade else {}),
                    **({"profile": extracted} if extracted else {})},
    )
    db.add(doc)

    # Prefill the profile, but never overwrite a value the student typed
    # themselves -- they know their own transcript better than Tesseract does.
    #
    # Resumes are excluded on purpose: their extraction goes to the form for
    # review first, and writing it into the session here would commit data the
    # student has not seen yet.
    if kind not in ("resume", "cv") and grade and grade.gpa_4 is not None:
        profile = dict(session.profile or {})
        if profile.get("gpa_4") is None:
            profile["gpa_4"] = grade.gpa_4
            profile["gpa_source"] = "ocr"
            profile["gpa_confidence"] = grade.confidence
            session.profile = profile

    await db.commit()
    await db.refresh(doc)

    return {
        "document_id": str(doc.id),
        "pages": result.pages,
        "ocr_confidence": result.confidence,
        "grade": grade.as_dict() if grade else None,
        # Structured profile for the editable form. Null when extraction was
        # unavailable, which the client treats as "fill it in yourself".
        "profile": extracted,
        # The UI uses this to decide between "we read your GPA as 3.6" and
        # "we could not read this — please type it in".
        "needs_confirmation": grade is None or grade.confidence < 0.7,
        # 100 means the PDF had a real text layer, so these are the document's
        # own characters rather than a recognition guess.
        "text_layer": result.confidence >= 100,
    }
