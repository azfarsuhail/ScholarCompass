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
import re
import time
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from .. import cache
from ..config import settings
from ..db import SessionLocal, get_db
from ..limits import MATCH_STREAM_LIMIT, limiter
from ..matching.filters import Candidate, relax
from ..matching.scoring import prompt_key, score_stream
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
        # ISO-8601 explicitly, not left to str(datetime): that renders
        # "2026-09-13 10:00:00+00:00" with a SPACE, which Safari refuses to
        # parse in `new Date(...)`. The freshness badge would read "Invalid
        # Date" for a slice of users and nowhere else would notice.
        #
        # `deadline` deliberately stays a real date object -- filters.py
        # compares it -- and is stringified at the JSON boundary instead.
        "last_verified_at": s.last_verified_at.isoformat() if s.last_verified_at else None,
        # Lets the UI distinguish "the publisher announces this later" from
        # "we could not find a deadline". See ingest/catalogue.py.
        "deadline_note": (s.raw or {}).get("deadline_note"),
        # Domain only. The logo is hotlinked from Brandfetch's CDN by the
        # browser, so no image bytes ever touch this 512MB container.
        "provider_domain": s.provider_domain or _domain_of(s.source_url),
        "min_work_experience_hours": s.min_work_experience_hours,
        "return_obligation": s.return_obligation,
        "entry_requirement": s.entry_requirement,
    }


def _domain_of(url: str | None) -> str | None:
    """Fallback logo domain, derived from the application URL."""
    m = re.match(r"https?://([^/:?#]+)", url or "")
    return m.group(1).lower().removeprefix("www.") if m else None


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


# Everything the client is allowed to write into the session profile.
#
# This set is a real filter boundary, not bookkeeping: a key missing from here
# is accepted by the form, sent over the wire, and then silently dropped -- so
# any matcher input that depends on it can never fire in production. Keep it
# in step with matching/filters.py and web/lib/schema.ts.
PROFILE_FIELDS = frozenset({
    "degree_level", "fields_of_study", "gpa_4", "gpa_source", "gpa_confidence",
    "passport_iso3", "age", "funding_preference", "language_scores",
    "target_countries", "institution", "skills", "experience",
    # Chevening-style awards reject outright below a stated hours figure, so
    # this is a filter input rather than a preference.
    "work_experience_hours",
})


def merge_profile(profile: dict, payload: dict) -> dict:
    """Fold an untrusted payload into a session profile.

    Pure, so the boundary that decides which student facts survive can be
    tested without a database -- the same reason filters.py is a pure function.
    """
    profile = dict(profile)
    profile.update({k: v for k, v in payload.items() if k in PROFILE_FIELDS})

    # Free text from an untrusted client, landing in a JSONB column. Capped
    # here rather than trusted to respect the form's own limits -- the form is
    # not the only thing that can call this endpoint.
    if "skills" in profile:
        raw = profile["skills"]
        profile["skills"] = (
            [str(s)[:60] for s in raw][:30] if isinstance(raw, list) else []
        )
    if "experience" in profile:
        raw = profile["experience"]
        profile["experience"] = (
            [
                {
                    "role": str(e.get("role") or "")[:120],
                    "organisation": str(e.get("organisation") or "")[:120],
                    "period": str(e["period"])[:60] if e.get("period") else None,
                }
                for e in raw
                if isinstance(e, dict)
            ][:10]
            if isinstance(raw, list)
            else []
        )
    if isinstance(profile.get("institution"), str):
        profile["institution"] = profile["institution"][:160]

    # A GPA the student typed outranks one we guessed from a scan.
    if "gpa_4" in payload and "gpa_source" not in payload:
        profile["gpa_source"] = "user"
        profile.pop("gpa_confidence", None)

    return profile


def _profile_fingerprint(profile: dict) -> str:
    """Canonical form of a profile, for addressing a cached result set.

    Sorted keys so that two identical profiles built in a different order hash
    the same; `default=str` so a stray date cannot make the fingerprint throw.
    """
    return json.dumps(profile, sort_keys=True, default=str)


def _explanation(run_id, candidate, index: int, scored: dict, *, cached: bool):
    """One MatchExplanation row. Cached and fresh scores are stored alike so a
    run stays fully explainable regardless of where its scores came from."""
    return MatchExplanation(
        run_id=run_id,
        scholarship_id=candidate.scholarship["id"],
        entered_at_level=candidate.level,
        deterministic_rank=index,
        semantic_score=scored.get("score"),
        rationale=scored.get("rationale"),
        matched_criteria=scored.get("matched_criteria") or [],
        gaps=scored.get("gaps") or [],
        model="groq (cached)" if cached else "groq",
    )


@router.put("/profile")
async def update_profile(
    payload: dict,
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Merge fields into the session profile. Progressive by design."""
    profile = merge_profile(dict(session.profile or {}), payload)

    session.profile = profile
    if isinstance(profile.get("passport_iso3"), str):
        session.passport_iso3 = profile["passport_iso3"].upper()[:3]
    await db.commit()
    return {"profile": profile}


@router.get("/match/stream")
@limiter.limit(MATCH_STREAM_LIMIT)
async def match_stream(
    # slowapi resolves its bucket from this parameter by NAME -- rename it and
    # the limit silently stops applying rather than failing loudly.
    request: Request,
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    profile = dict(session.profile or {})
    session_id = session.id
    cfg = settings()

    t0 = time.perf_counter()

    # --- deterministic half ------------------------------------------------
    # A repeat of the same profile skips both the Neon round-trip and the
    # ladder, which together are the whole first-paint budget.
    det_key = cache.key_for(
        "deterministic", cfg.min_results_before_relaxing, _profile_fingerprint(profile)
    )
    cached = await cache.get(db, det_key)
    if cached:
        # Rebuilt, not re-relaxed. The scholarship dicts in here have had their
        # dates flattened to strings by JSONB, so they must not go back through
        # filters.py -- see cache.jsonable.
        candidates = [
            Candidate(
                scholarship=c["scholarship"],
                level=c["level"],
                gaps=list(c.get("gaps") or []),
                notes=list(c.get("notes") or []),
            )
            for c in (cached.get("candidates") or [])
        ]
        counts = cached.get("counts") or {}
        deepest = cached.get("deepest") or "R0"
        corpus_size = cached.get("corpus_size")
    else:
        rows = await _coarse_candidates(db, profile)
        corpus_size = len(rows)
        candidates, counts, deepest = relax(
            profile,
            rows,
            min_results=cfg.min_results_before_relaxing,
            today=date.today(),
        )

    deterministic_ms = int((time.perf_counter() - t0) * 1000)
    if deterministic_ms > cfg.deterministic_budget_ms:
        # The deterministic half is the one latency promise this product makes.
        # Recording it on MatchRun proves it after the fact; logging it here is
        # what makes a regression visible without querying the table.
        log.warning(
            "deterministic pass took %dms over a %dms budget (%s candidates scanned)",
            deterministic_ms,
            cfg.deterministic_budget_ms,
            corpus_size if corpus_size is not None else "cached",
        )

    # --- which fit judgements do we already own? ---------------------------
    # ONE query for all of them. Forty individual lookups against a
    # network-attached database would cost more than the Groq calls they save.
    score_keys = [prompt_key(profile, c) for c in candidates]
    score_hits = await cache.get_many(db, score_keys)

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
            # Surfaced rather than hidden: a judge (or a student wondering why
            # the second search was instant) can see exactly what was reused.
            "cache": {
                "deterministic_hit": cached is not None,
                "scores_cached": len(score_hits),
            },
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

        # Store the ladder's output now rather than before the first byte, so a
        # cache MISS pays nothing on the latency path it exists to protect.
        if cached is None:
            async with SessionLocal() as w:
                try:
                    await w.execute(cache.put_stmt(
                        det_key, "deterministic",
                        {
                            "candidates": [
                                {"scholarship": c.scholarship, "level": c.level,
                                 "gaps": c.gaps, "notes": c.notes}
                                for c in candidates
                            ],
                            "counts": counts, "deepest": deepest,
                            "corpus_size": corpus_size,
                        },
                        cache.DETERMINISTIC_TTL,
                    ))
                    await w.commit()
                except Exception as e:  # noqa: BLE001 - a cache is never load-bearing
                    log.warning("deterministic cache write failed: %s", e)

        # Cached scores cost nothing, so they go out before a single Groq call.
        if score_hits:
            async with SessionLocal() as w:
                for i, key in enumerate(score_keys):
                    scored = score_hits.get(key)
                    if scored is None:
                        continue
                    enriched += 1
                    yield _sse("enrichment", {"index": i, "cached": True, **scored})
                    w.add(_explanation(run_id, candidates[i], i, scored, cached=True))
                try:
                    await w.commit()
                except Exception as e:  # noqa: BLE001
                    log.warning("persisting cached explanations failed: %s", e)

        # Only the misses reach the model.
        misses = [(i, c) for i, c in enumerate(candidates) if score_keys[i] not in score_hits]
        try:
            async for i, scored in score_stream(
                profile,
                [c for _, c in misses],
                indices=[i for i, _ in misses],
            ):
                if await request.is_disconnected():
                    break
                if scored is None:
                    continue
                enriched += 1
                yield _sse("enrichment", {"index": i, "cached": False, **scored})
                # A fresh session per write: the request-scoped one may be
                # mid-teardown by the time late enrichments land. The cache
                # entry rides along in the same transaction, so remembering
                # this answer costs no extra round-trip.
                async with SessionLocal() as w:
                    w.add(_explanation(run_id, candidates[i], i, scored, cached=False))
                    await w.execute(cache.put_stmt(
                        score_keys[i], "match_score", scored,
                        cache.MATCH_SCORE_TTL, version=cfg.match_model,
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

        yield _sse("done", {
            "enriched": enriched,
            "total": len(candidates),
            "from_cache": len(score_hits),
        })

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
