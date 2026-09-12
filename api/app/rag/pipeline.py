"""Visa RAG: retrieve official text, then answer strictly from it.

Retrieval is Postgres full-text search (see VisaSourceChunk for why lexical
beats vectors on this corpus). Generation is Groq, constrained hard:

  * Every claim must come from a supplied chunk.
  * The answer carries citations, and an answer with no citations is discarded
    rather than shown. An uncited visa instruction is worse than no answer --
    a student can act on it, be wrong, and lose a visa fee or a semester.
  * The structured Orizn `requirement` always wins over anything the model
    infers from prose. The model adds procedure and nuance; it does not get to
    overturn the yes/no.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm import complete_json
from ..models import VisaEvidence, VisaSourceChunk

log = logging.getLogger(__name__)

TOP_K = 6
SNIPPET_CHARS = 1200
RAG_TTL = timedelta(days=7)

SYSTEM = """You answer student visa questions using ONLY the numbered sources provided.

Return JSON:
  {"summary": "<=4 sentences of practical guidance",
   "student_route_notes": "what specifically applies to a student visa, or null",
   "citations": [{"n": <source number>, "quote": "<=200 chars verbatim"}]}

Hard rules:
- Every factual claim must be supported by a source you cite.
- Quotes must be copied verbatim from the source text. Never paraphrase inside
  a quote.
- If the sources do not answer the question, return an empty citations array
  and say plainly in the summary that the sources do not cover it.
- Do not restate the overall visa-required/visa-free verdict; that is already
  established elsewhere. Explain process, documents and timing instead.
- Never guarantee an outcome. Never invent fees, durations or document names."""


async def retrieve(
    db: AsyncSession, destination: str, passport: str | None, query: str
) -> list[VisaSourceChunk]:
    """Top-K chunks for this destination, preferring passport-specific pages."""
    ts = func.plainto_tsquery("english", query)
    stmt = (
        select(VisaSourceChunk, func.ts_rank(VisaSourceChunk.search_vector, ts).label("rank"))
        .where(VisaSourceChunk.destination_iso3 == destination.upper())
        .where(VisaSourceChunk.search_vector.op("@@")(ts))
    )
    if passport:
        # A page written for this nationality, or a general one. Never a page
        # written for a DIFFERENT nationality -- those rules do not transfer.
        stmt = stmt.where(
            or_(
                VisaSourceChunk.passport_iso3 == passport.upper(),
                VisaSourceChunk.passport_iso3.is_(None),
            )
        )
    stmt = stmt.order_by(
        # Nationality-specific sources outrank general ones at equal relevance.
        VisaSourceChunk.passport_iso3.is_(None),
        func.ts_rank(VisaSourceChunk.search_vector, ts).desc(),
    ).limit(TOP_K)

    return [row[0] for row in (await db.execute(stmt)).all()]


def _format_sources(chunks: list[VisaSourceChunk]) -> str:
    return "\n\n".join(
        f"[{i}] {c.title or c.publisher or c.url}\nURL: {c.url}\n"
        f"{(c.content or '')[:SNIPPET_CHARS]}"
        for i, c in enumerate(chunks, start=1)
    )


async def answer(
    db: AsyncSession, passport: str, destination: str, question: str | None = None
) -> dict | None:
    """Produce a cited narrative answer, or None if we cannot support one."""
    q = question or f"student visa requirements documents application process {destination}"
    chunks = await retrieve(db, destination, passport, q)
    if not chunks:
        log.info("rag: no sources for %s->%s", passport, destination)
        return None

    data = await complete_json(
        SYSTEM,
        f"Student passport: {passport}. Destination: {destination}.\n"
        f"Question: {q}\n\nSOURCES\n{_format_sources(chunks)}",
        max_tokens=700,
    )
    if not isinstance(data, dict):
        return None

    # Resolve the model's source numbers back to real URLs, dropping any
    # citation that points at a source we never supplied -- the cheapest
    # available check against a fabricated reference.
    resolved = []
    for c in data.get("citations") or []:
        try:
            idx = int(c.get("n")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(chunks):
            src = chunks[idx]
            resolved.append({
                "quote": str(c.get("quote") or "")[:200],
                "url": src.url,
                "publisher": src.publisher,
                "retrieved_at": src.retrieved_at.isoformat() if src.retrieved_at else None,
            })

    if not resolved:
        log.info("rag: answer had no resolvable citations; discarding")
        return None

    return {
        "summary": str(data.get("summary") or "").strip()[:1200],
        "student_route_notes": (str(data.get("student_route_notes")).strip()[:800]
                                if data.get("student_route_notes") else None),
        "citations": resolved,
    }


async def enrich_evidence(db: AsyncSession, passport: str, destination: str) -> dict | None:
    """Attach (and cache) the RAG narrative onto the cached VisaEvidence row."""
    p, d = passport.upper(), destination.upper()
    row = (
        await db.execute(
            select(VisaEvidence).where(
                VisaEvidence.passport_iso3 == p, VisaEvidence.destination_iso3 == d
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is not None and row.summary and row.fetched_at and row.fetched_at > now - RAG_TTL:
        return {
            "summary": row.summary,
            "student_route_notes": row.student_route_notes,
            "citations": row.citations or [],
        }

    result = await answer(db, p, d)
    if result is None:
        return None

    if row is not None:
        row.summary = result["summary"]
        row.student_route_notes = result["student_route_notes"]
        row.citations = result["citations"]
        await db.commit()
    return result
