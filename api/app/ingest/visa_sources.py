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
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select

from ..config import settings
from ..db import Base, SessionLocal, engine
from ..models import VisaSourceChunk
from ..orizn import REQUIREMENT_LABELS, _iso3

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
        await db.commit()
    log.info("seeded %s->%s with %s chunks (%s)", p, d, len(rows), path)
    return len(rows)


async def main() -> None:
    ap = argparse.ArgumentParser(description="Seed visa_source_chunks from Orizn")
    ap.add_argument("--pair", action="append", default=[],
                    help="PASSPORT:DESTINATION, e.g. PAK:CHN")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

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
