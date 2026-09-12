"""Progressive matching over Server-Sent Events.

The contract this endpoint exists to keep: deterministic results reach the
screen fast, and AI enrichment arrives afterwards without blocking them.

  event: run        the run opened, with per-rung counts
  event: match      one eligible scholarship (deterministic, no LLM)
  event: enrichment one LLM score/rationale, keyed back to a match
  event: done       finished

So a student with no Groq key, a slow model, or a dead upstream still gets a
complete, ranked, explainable result set -- just without the prose. Every
event after `match` is additive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from ..db import SessionLocal, get_db
from ..matching.filters import relax
from ..matching.scoring import score_stream
from ..models import AnonSession, MatchExplanation, MatchRun, Scholarship
from ..session import current_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["match"])

# Ceiling on the coarse SQL pull. The ladder runs in Python over this set.
CANDIDATE_CAP = 500


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _row_to_dict(s: Scholarship) -> dict:
    return {
        "id": str(s.id), "slug": s.slug, "title": s.title, "provider": s.provider,
        "host_country_iso3": s.host_country_iso3,
        "degree_levels": list(s.degree_levels or []),
        "fields_of_study": list(s.fields_of_study or []),
        "min_gpa_4": float(s.min_gpa_4) if s.min_gpa_4 is not None else None,
        "min_language_score": s.min_language_score or {},
        "eligible_nationalities": list(s.eligible_nationalities or []),
        "excluded_nationalities": list(s.excluded_nationalities or []),
        "max_age": s.max_age, "funding_type": s.funding_type,
        "deadline": s.deadline, "is_rolling": s.is_rolling,
        "source_url": s.source_url,
        "last_verified_at": s.last_verified_at,
        # Lets the UI distinguish "the publisher announces this later" from
        # "we could not find a deadline". See ingest/catalogue.py.
        "deadline_note": (s.raw or {}).get("deadline_note"),
    }


async def _coarse_candidates(db: AsyncSession, profile: dict) -> list[dict]:
    """One query, not six.

    Neon is network-attached; six sequential round-trips (one per rung) could
    eat the latency budget on their own. So SQL applies only the constraints
    that NO rung ever relaxes -- nationality and degree level -- and the ladder
    then runs in memory, which also makes per-rung tagging exact.
    """
    stmt = select(Scholarship)
    passport = (profile.get("passport_iso3") or "").upper()
    if len(passport) == 3:
        stmt = stmt.where(
            text("NOT (:p = ANY(scholarships.excluded_nationalities))").bindparams(p=passport)
        ).where(
            text(
                "(cardinality(scholarships.eligible_nationalities) = 0 "
                "OR :p2 = ANY(scholarships.eligible_nationalities))"
            ).bindparams(p2=passport)
        )
    level = (profile.get("degree_level") or "").lower()
    if level:
        stmt = stmt.where(
            text(
                "(cardinality(scholarships.degree_levels) = 0 "
                "OR :lvl = ANY(scholarships.degree_levels))"
            ).bindparams(lvl=level)
        )
    rows = (await db.execute(stmt.limit(CANDIDATE_CAP))).scalars().all()
    return [_row_to_dict(r) for r in rows]


@router.put("/profile")
async def update_profile(
    payload: dict,
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Merge fields into the session profile. Progressive by design."""
    profile = dict(session.profile or {})
    allowed = {
        "degree_level", "fields_of_study", "gpa_4", "gpa_source", "gpa_confidence",
        "passport_iso3", "age", "funding_preference", "language_scores",
        "target_countries",
    }
    profile.update({k: v for k, v in payload.items() if k in allowed})

    # A GPA the student typed outranks one we guessed from a scan.
    if "gpa_4" in payload and "gpa_source" not in payload:
        profile["gpa_source"] = "user"
        profile.pop("gpa_confidence", None)

    session.profile = profile
    if isinstance(profile.get("passport_iso3"), str):
        session.passport_iso3 = profile["passport_iso3"].upper()[:3]
    await db.commit()
    return {"profile": profile}


@router.get("/match/stream")
async def match_stream(
    request: Request,
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    profile = dict(session.profile or {})
    session_id = session.id

    t0 = time.perf_counter()
    rows = await _coarse_candidates(db, profile)
    candidates, counts, deepest = relax(profile, rows, today=date.today())
    deterministic_ms = int((time.perf_counter() - t0) * 1000)

    run = MatchRun(
        session_id=session_id, status="running", relaxation_level=deepest,
        level_counts=counts, candidate_count=len(candidates),
        deterministic_ms=deterministic_ms, profile_snapshot=profile,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    run_id = run.id

    async def stream():
        yield _sse("run", {
            "run_id": str(run_id),
            "relaxation_level": deepest,
            "level_counts": counts,
            "candidate_count": len(candidates),
            "deterministic_ms": deterministic_ms,
        })

        for i, c in enumerate(candidates):
            yield _sse("match", {
                "index": i,
                "level": c.level,
                "is_exact": c.is_exact,
                "gaps": c.gaps,
                "notes": c.notes,
                "scholarship": c.scholarship,
            })

        # Deterministic half is on screen. Everything below is additive.
        enriched = 0
        t1 = time.perf_counter()
        try:
            async for i, scored in score_stream(profile, candidates):
                if await request.is_disconnected():
                    break
                if scored is None:
                    continue
                enriched += 1
                yield _sse("enrichment", {"index": i, **scored})
                # A fresh session per write: the request-scoped one may be
                # mid-teardown by the time late enrichments land.
                async with SessionLocal() as w:
                    w.add(MatchExplanation(
                        run_id=run_id,
                        scholarship_id=candidates[i].scholarship["id"],
                        entered_at_level=candidates[i].level,
                        deterministic_rank=i,
                        semantic_score=scored["score"],
                        rationale=scored["rationale"],
                        matched_criteria=scored["matched_criteria"],
                        gaps=scored["gaps"],
                        model="groq",
                    ))
                    await w.commit()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - enrichment must never break the stream
            log.warning("enrichment failed for run %s: %s", run_id, e)

        async with SessionLocal() as w:
            r = await w.get(MatchRun, run_id)
            if r is not None:
                r.status = "complete"
                r.enrichment_ms = int((time.perf_counter() - t1) * 1000)
                r.completed_at = datetime.now(timezone.utc)
                await w.commit()

        yield _sse("done", {"enriched": enriched, "total": len(candidates)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Without this, nginx-style proxies buffer the whole response and
            # the progressive stream degrades into one slow blob.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
