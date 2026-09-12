"""Visa endpoint: structured verdict from Orizn, narrative from RAG.

The two halves are deliberately unequal. Orizn's `requirement` is the answer;
the RAG narrative is commentary. If they ever disagree, the structured value
wins and the narrative is shown as supporting detail, never as a correction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AnonSession
from ..orizn import REQUIREMENT_LABELS, get_or_fetch
from ..rag.pipeline import enrich_evidence
from ..session import current_session
from ..visa_readiness import readiness

router = APIRouter(prefix="/v1/visa", tags=["visa"])


@router.get("/check")
async def check(
    destination: str = Query(..., min_length=3, max_length=3),
    passport: str | None = Query(None, min_length=3, max_length=3),
    explain: bool = Query(False, description="Also run the RAG narrative"),
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Visa requirement for a passport/destination pair.

    `passport` falls back to the session profile so the caller does not have to
    resend it -- but it is never inferred from anything else.
    """
    p = (passport or session.passport_iso3 or "").upper()
    if len(p) != 3 or not p.isalpha():
        raise HTTPException(400, "A 3-letter passport country code is required.")
    d = destination.upper()
    if not d.isalpha():
        raise HTTPException(400, "Destination must be an ISO 3166-1 alpha-3 code.")

    try:
        check = await get_or_fetch(db, p, d)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    if check is None:
        # Honest 'unknown' rather than a guess. A fabricated visa verdict is
        # the most expensive possible error for a student.
        return {
            "passport": p, "destination": d, "requirement": None,
            "label": "Unknown", "available": False,
            "message": "We could not verify this route right now. "
                       "Check with the embassy before booking anything.",
        }

    out = {
        "passport": p,
        "destination": d,
        "requirement": check.requirement,
        "label": check.label,
        "visa_free_days": check.visa_free_days,
        "source_last_verified": check.last_verified,
        "stale": check.stale,
        "available": True,
        "source": "orizn",
        # Surfaced, not buried: the free plan is licensed for evaluation only.
        "license": (check.payload or {}).get("license"),
    }

    # Structured checklist: documents, proof of funds, process, dates.
    # Cheap (a single indexed read of the corpus) so it rides along with every
    # check rather than needing a second round-trip from the card.
    detail = await readiness(db, p, d)
    if detail:
        out["readiness"] = detail

    if explain:
        narrative = await enrich_evidence(db, p, d)
        if narrative:
            out["explanation"] = narrative

    return out


@router.get("/requirements")
async def requirement_labels() -> dict:
    """The enum the UI renders. Mirrors Orizn's `requirement` values exactly."""
    return {"requirements": REQUIREMENT_LABELS}
