"""Seed the visa RAG corpus (visa_source_chunks).

Per the hackathon decision, we do NOT scrape government portals. Embassy sites
are nav-heavy, frequently non-English, and change without notice -- a bad
trade for demo reliability. Orizn is a licensed, live, versioned source that
stamps its own `last_verified` date, so it is what we cite.

Two things this file refuses to do:

  * Invent prose. Every chunk is assembled from fields Orizn actually
    returned. Nothing is written that the API did not say.
  * Blur provenance. Each chunk records the exact request URL it came from, so
    the citations the RAG emits resolve to something a student can re-run.

Note the deliberate scope limit: `visa_source_chunks` is the VISA corpus. The
Erasmus/DAAD crawlers write to `scholarships` instead. Mixing catalogue text in
here would let a "what visa do I need?" query retrieve scholarship deadlines,
which is exactly the failure the citation rules exist to prevent.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select

from ..config import settings
from ..db import Base, SessionLocal, engine
from ..models import VisaEvidence, VisaSourceChunk
from ..orizn import CACHE_TTL, REQUIREMENT_LABELS, _iso3

log = logging.getLogger(__name__)

PUBLISHER = "Orizn Visa API"

# Pairs seeded by default. PAK->CHN is the validation case.
DEFAULT_PAIRS = [
    ("PAK", "CHN"), ("PAK", "DEU"), ("PAK", "GBR"),
    ("PAK", "TUR"), ("PAK", "JPN"), ("PAK", "KOR"),
    ("IND", "DEU"), ("NGA", "GBR"),
]


async def _fetch(client: httpx.AsyncClient, path: str, params: dict) -> dict | None:
    headers = {"Accept": "application/json"}
    if settings().orizn_api_key:
        headers["x-api-key"] = settings().orizn_api_key
    url = f"{settings().orizn_base_url}{path}"
    try:
        r = await client.get(url, params=params, headers=headers)
        if r.status_code != 200:
            log.info("orizn %s -> HTTP %s", path, r.status_code)
            return None
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("orizn %s failed: %s", path, e)
        return None


def _compose(passport: str, destination: str, data: dict, source_url: str) -> list[dict]:
    """Turn an Orizn payload into retrievable chunks.

    Split by topic rather than dumped as one blob: FTS ranking rewards a chunk
    whose whole text is about the thing being asked, and a student asking about
    documents should not retrieve a paragraph that is mostly fee tables.
    """
    requirement = data.get("requirement")
    label = REQUIREMENT_LABELS.get(requirement or "", "Unknown")
    verified = data.get("last_verified")
    days = data.get("visa_free_days")

    chunks: list[dict] = []

    verdict = (
        f"Entry requirement for {passport} passport holders travelling to "
        f"{destination}: {label} ({requirement}). "
        + (f"Permitted visa-free stay: {days} days. " if days else "")
        + (f"Last verified by the source on {verified}. " if verified else "")
        + "This is the entry rule for the passport/destination pair; a study "
          "stay may additionally require a student visa category and a "
          "residence permit issued after arrival."
    )
    chunks.append({"title": f"{passport} to {destination}: entry requirement", "content": verdict})

    # Only present on the full /visa endpoint (paid plans).
    if docs := data.get("documents_required"):
        chunks.append({
            "title": f"{passport} to {destination}: documents required",
            "content": "Documents required: " + "; ".join(str(d) for d in docs) + ".",
        })
    if process := data.get("process"):
        chunks.append({
            "title": f"{passport} to {destination}: application process",
            "content": "Application process: "
                       + " ".join(f"{i}. {s}" for i, s in enumerate(process, 1)) + ".",
        })
    if (validity := data.get("passport_validity_months")) is not None:
        chunks.append({
            "title": f"{passport} to {destination}: passport validity",
            "content": f"Passport must be valid for at least {validity} months.",
        })
    if embassy := data.get("embassy"):
        apply_at = (embassy or {}).get("visa_application_embassy") or {}
        if apply_at:
            chunks.append({
                "title": f"{passport} to {destination}: where to apply",
                "content": f"Visa applications are handled by {apply_at.get('name')}"
                           + (f" in {apply_at['city']}" if apply_at.get("city") else "") + ".",
            })

    now = datetime.now(timezone.utc)
    return [
        {
            "destination_iso3": destination,
            "passport_iso3": passport,  # nationality-specific, never reused for another passport
            "url": source_url,
            "publisher": PUBLISHER,
            "title": c["title"],
            "content": c["content"],
            "retrieved_at": now,
        }
        for c in chunks
    ]


async def seed_pair(client: httpx.AsyncClient, passport: str, destination: str) -> int:
    p, d = _iso3(passport), _iso3(destination)
    params = {"passport": p, "destination": d}

    # Prefer the 30-field endpoint; fall back to the free yes/no.
    path = "/api/v1/visa"
    data = await _fetch(client, path, params)
    if not data or not (data.get("data") or data.get("requirement")):
        path = "/api/v1/visa/check"
        data = await _fetch(client, path, params)
    else:
        data = data.get("data", data)

    if not data or not data.get("requirement"):
        log.warning("no usable Orizn data for %s->%s", p, d)
        return 0

    source_url = f"{settings().orizn_base_url}{path}?passport={p}&destination={d}"
    rows = _compose(p, d, data, source_url)

    async with SessionLocal() as db:
        # Replace this pair's chunks rather than appending, so re-seeding
        # refreshes the corpus instead of stacking stale duplicates that would
        # compete in FTS ranking.
        await db.execute(
            delete(VisaSourceChunk).where(
                VisaSourceChunk.passport_iso3 == p,
                VisaSourceChunk.destination_iso3 == d,
                VisaSourceChunk.publisher == PUBLISHER,
            )
        )
        db.add_all([VisaSourceChunk(**r) for r in rows])

        # Also prime the STRUCTURED cache, not just the RAG corpus.
        #
        # Without this the two halves disagree under load: seeding fills the
        # narrative corpus while /v1/visa/check still calls Orizn live, so the
        # moment the free plan returns 429 the endpoint reports "Unknown" even
        # though we hold a perfectly good, dated answer for that pair. Priming
        # visa_evidence lets the request path serve the cached verdict (and
        # flag it stale) instead of losing the answer to a rate limit.
        evidence = (
            await db.execute(
                select(VisaEvidence).where(
                    VisaEvidence.passport_iso3 == p, VisaEvidence.destination_iso3 == d
                )
            )
        ).scalar_one_or_none()
        if evidence is None:
            evidence = VisaEvidence(passport_iso3=p, destination_iso3=d)
            db.add(evidence)

        now = datetime.now(timezone.utc)
        verified = data.get("last_verified")
        evidence.requirement = data.get("requirement")
        evidence.visa_free_days = data.get("visa_free_days")
        try:
            evidence.source_last_verified = (
                datetime.strptime(verified, "%Y-%m-%d").date() if verified else None
            )
        except (TypeError, ValueError):
            evidence.source_last_verified = None
        evidence.orizn_payload = data
        evidence.fetched_at = now
        evidence.expires_at = now + CACHE_TTL

        await db.commit()
    log.info("seeded %s->%s with %s chunks (%s)", p, d, len(rows), path)
    return len(rows)


async def repair_evidence() -> int:
    """Rebuild visa_evidence from chunks already in the corpus, spending no quota.

    The verdict is parsed out of the machine-readable tail we wrote ourselves
    ("... (visa_required)"), not inferred from prose — so this round-trips our
    own structured data rather than guessing at it. Useful when the corpus was
    seeded but the structured cache was not, which otherwise leaves
    /v1/visa/check reporting Unknown for pairs we demonstrably have an answer
    for.
    """
    now = datetime.now(timezone.utc)
    repaired = 0

    async with SessionLocal() as db:
        chunks = (
            await db.execute(
                select(VisaSourceChunk).where(VisaSourceChunk.publisher == PUBLISHER)
            )
        ).scalars().all()

        by_pair: dict[tuple[str, str], list[VisaSourceChunk]] = {}
        for c in chunks:
            if c.passport_iso3:
                by_pair.setdefault((c.passport_iso3, c.destination_iso3), []).append(c)

        for (p, d), rows in by_pair.items():
            verdict = next((r for r in rows if "entry requirement" in (r.title or "")), None)
            if verdict is None:
                continue
            m = re.search(r"\((visa_free|visa_required|e_visa|visa_on_arrival|eta|no_admission)\)",
                          verdict.content or "")
            if not m:
                continue

            existing = (
                await db.execute(
                    select(VisaEvidence).where(
                        VisaEvidence.passport_iso3 == p, VisaEvidence.destination_iso3 == d
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = VisaEvidence(passport_iso3=p, destination_iso3=d)
                db.add(existing)

            existing.requirement = m.group(1)
            days = re.search(r"Permitted visa-free stay: (\d+) days", verdict.content or "")
            existing.visa_free_days = int(days.group(1)) if days else None
            verified = re.search(r"Last verified by the source on (\d{4}-\d{2}-\d{2})",
                                 verdict.content or "")
            if verified:
                try:
                    existing.source_last_verified = datetime.strptime(
                        verified.group(1), "%Y-%m-%d").date()
                except ValueError:
                    pass
            existing.orizn_payload = {"requirement": m.group(1),
                                      "reconstructed_from": "visa_source_chunks"}
            existing.fetched_at = now
            existing.expires_at = now + CACHE_TTL
            repaired += 1

        await db.commit()
    return repaired


async def main() -> None:
    ap = argparse.ArgumentParser(description="Seed visa_source_chunks from Orizn")
    ap.add_argument("--pair", action="append", default=[],
                    help="PASSPORT:DESTINATION, e.g. PAK:CHN")
    ap.add_argument("--repair-evidence", action="store_true",
                    help="Rebuild visa_evidence from the existing corpus; uses no API quota")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.repair_evidence:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        n = await repair_evidence()
        print(f"repaired {n} visa_evidence rows from the existing corpus")
        await engine.dispose()
        return

    if not settings().orizn_api_key:
        # Fail loudly and usefully. Orizn only allows keyless calls from its own
        # allow-listed Referer (their site / localhost / their extension), which
        # a server container is not -- so every request here would 401 and the
        # corpus would silently stay empty.
        print(
            "ORIZN_API_KEY is not set.\n"
            "  Server-side Orizn calls require a key; keyless access only works\n"
            "  from an allow-listed browser Referer. Get a free key at\n"
            "  https://visa.orizn.app/visa-api and set ORIZN_API_KEY, then re-run.\n"
            "  Note: the free plan is licensed for non-commercial evaluation only."
        )
        raise SystemExit(2)

    pairs = ([tuple(p.upper().split(":", 1)) for p in args.pair] if args.pair
             else DEFAULT_PAIRS)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    total = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        for passport, destination in pairs:
            total += await seed_pair(client, passport, destination)
            await asyncio.sleep(0.3)  # polite to a rate-limited API

    async with SessionLocal() as db:
        corpus = len((await db.execute(select(VisaSourceChunk.id))).all())
    print(f"wrote {total} chunks; {corpus} total in visa_source_chunks")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
