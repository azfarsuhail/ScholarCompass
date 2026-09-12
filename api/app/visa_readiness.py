"""Structured 'visa readiness' for a passport/destination pair.

Source of truth is `visa_source_chunks` — the same corpus the RAG answers from
— rather than `visa_evidence.orizn_payload`. That is deliberate: the payload
column currently holds only the requirement for pairs that were rebuilt with
`--repair-evidence`, while the chunks carry the full documents/process text.

Parsing is safe here because WE wrote that text (see ingest/visa_sources.py
_compose), so the "Documents required: a; b; c." shape is our own contract,
not scraped prose we are guessing at. If a chunk ever stops matching, the
field comes back empty rather than half-parsed.

Nothing in this module invents a requirement. Every string returned appears
verbatim in a stored chunk, and each response carries the URL it came from so
a student can re-check it.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import VisaEvidence, VisaSourceChunk

# Items that constitute proof of funds. Insurance and fees are deliberately
# NOT here: they are costs a student must meet, not evidence of means, and
# conflating them would overstate what the source actually asks for.
_FINANCIAL = re.compile(r"fund|financ|bank|sponsor|sufficient|scholarship|stipend", re.I)


def _after(content: str, prefix: str) -> str | None:
    if not content or not content.lower().startswith(prefix.lower()):
        return None
    return content[len(prefix) :].strip().rstrip(".")


def _parse_documents(content: str) -> list[str]:
    body = _after(content, "Documents required:")
    if not body:
        return []
    return [d.strip() for d in body.split(";") if d.strip()]


def _parse_process(content: str) -> list[str]:
    body = _after(content, "Application process:")
    if not body:
        return []
    # "1. Fill out the form 2. Gather documents" -> split on the numbering.
    parts = re.split(r"\s*\d+\.\s*", body)
    return [p.strip().rstrip(".") for p in parts if p.strip()]


def _parse_validity(content: str) -> int | None:
    text = content or ""
    # 0 is a real answer (the UK asks for no validity beyond the stay), so it
    # is reported as 0 rather than collapsed into "not stated" — the UI phrases
    # the two cases differently.
    if re.search(r"no passport validity is required", text, re.I):
        return 0
    m = re.search(r"at least (\d+) months", text, re.I)
    return int(m.group(1)) if m else None


async def readiness(db: AsyncSession, passport: str, destination: str) -> dict | None:
    """Everything a student needs to assemble, for one pair. None if unknown."""
    p, d = passport.upper(), destination.upper()

    chunks = (
        await db.execute(
            select(VisaSourceChunk).where(
                VisaSourceChunk.passport_iso3 == p,
                VisaSourceChunk.destination_iso3 == d,
            )
        )
    ).scalars().all()
    if not chunks:
        return None

    documents: list[str] = []
    process: list[str] = []
    validity: int | None = None
    retrieved: datetime | None = None
    sources: list[dict] = []

    for c in chunks:
        title = (c.title or "").lower()
        content = c.content or ""
        if "documents required" in title:
            documents = _parse_documents(content)
        elif "application process" in title:
            process = _parse_process(content)
        elif "passport validity" in title:
            validity = _parse_validity(content)
        if c.retrieved_at and (retrieved is None or c.retrieved_at > retrieved):
            retrieved = c.retrieved_at
        src = {"url": c.url, "publisher": c.publisher}
        if src not in sources:
            sources.append(src)

    evidence = (
        await db.execute(
            select(VisaEvidence).where(
                VisaEvidence.passport_iso3 == p, VisaEvidence.destination_iso3 == d
            )
        )
    ).scalar_one_or_none()

    return {
        "documents": documents,
        # A derived VIEW of `documents`, not a separate claim — these strings
        # are the same items, surfaced separately because proof of funds is the
        # requirement students most often miss.
        "financial": [doc for doc in documents if _FINANCIAL.search(doc)],
        "process": process,
        "passport_validity_months": validity,
        # Two distinct dates, never conflated. `source_last_verified` is the
        # publisher's own date; `retrieved_at` is merely when WE fetched it.
        # Presenting our fetch time as a verification date would overstate how
        # fresh the underlying rule is.
        "source_last_verified": (
            evidence.source_last_verified.isoformat()
            if evidence and evidence.source_last_verified
            else None
        ),
        "retrieved_at": retrieved.isoformat() if retrieved else None,
        "sources": sources,
    }


def _demo() -> None:
    """Self-check for the parsers. No database."""
    docs = _parse_documents(
        "Documents required: Valid passport (6 months minimum); Completed visa "
        "application form; Proof of sufficient funds; Travel insurance."
    )
    assert len(docs) == 4, docs
    assert docs[0] == "Valid passport (6 months minimum)"
    assert docs[-1] == "Travel insurance"

    financial = [d for d in docs if _FINANCIAL.search(d)]
    assert financial == ["Proof of sufficient funds"], financial
    # Insurance is a cost, not evidence of means — it must not be miscounted.
    assert "Travel insurance" not in financial

    steps = _parse_process(
        "Application process: 1. Fill out the visa application form 2. Gather "
        "required documents 3. Wait for processing."
    )
    assert steps == [
        "Fill out the visa application form",
        "Gather required documents",
        "Wait for processing",
    ], steps

    assert _parse_validity("Passport must be valid for at least 6 months.") == 6
    assert _parse_validity("no validity stated") is None
    # A genuine zero must survive as 0, not become None — "no extra validity
    # needed" and "we do not know" are different answers to a student.
    assert _parse_validity(
        "No passport validity is required beyond the length of the stay."
    ) == 0
    assert _parse_validity("Passport must be valid for at least 0 months.") == 0

    # A chunk that does not match our own contract yields nothing, rather than
    # a half-parsed list presented as fact.
    assert _parse_documents("Something else entirely") == []
    assert _parse_process("") == []

    print("visa readiness parser self-check passed")


if __name__ == "__main__":
    _demo()
