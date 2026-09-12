from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..db import get_db
from ..models import AnonSession, Document
from ..ocr import MAX_BYTES, extract
from ..session import current_session

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

    The upload itself is never persisted. It is read into memory, converted to
    text, and dropped when this handler returns -- so the worst case for a
    breach is the extracted grade, not a scan of someone's passport.
    """
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            415, f"Unsupported file type '{content_type or 'unknown'}'. "
                 "Upload a PDF or an image of your transcript.")

    data = await file.read()
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
    doc = Document(
        session_id=session.id,
        kind=kind,
        filename=file.filename,
        ocr_text=result.text[:20000],
        ocr_confidence=result.confidence,
        normalized=grade.as_dict() if grade else {},
    )
    db.add(doc)

    # Prefill the profile, but never overwrite a value the student typed
    # themselves -- they know their own transcript better than Tesseract does.
    if grade and grade.gpa_4 is not None:
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
        # The UI uses this to decide between "we read your GPA as 3.6" and
        # "we could not read this — please type it in".
        "needs_confirmation": grade is None or grade.confidence < 0.7,
    }
