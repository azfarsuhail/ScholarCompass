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
from datetime import date, datetime, timezone

import httpx
from dataclasses import dataclass
from sqlalchemy import delete, or_, select

from ..config import settings
from ..db import Base, SessionLocal, engine
from ..models import Scholarship, VisaEvidence, VisaSourceChunk
from ..orizn import CACHE_TTL, REQUIREMENT_LABELS, _iso3

log = logging.getLogger(__name__)

PUBLISHER = "Orizn Visa API"

# Pairs seeded by default. PAK->CHN is the validation case.
DEFAULT_PAIRS = [
    ("PAK", "CHN"), ("PAK", "DEU"), ("PAK", "GBR"),
    ("PAK", "TUR"), ("PAK", "JPN"), ("PAK", "KOR"),
    ("IND", "DEU"), ("NGA", "GBR"),
]


@dataclass
class Fetch:
    """One Orizn call. `status` is 0 for a transport error (no HTTP reply)."""

    data: dict | None
    status: int
    remaining: int | None = None

    @property
    def quota_exhausted(self) -> bool:
        return self.status == 429

    @property
    def transient(self) -> bool:
        """Worth skipping past rather than abandoning the run."""
        return self.status == 0 or 500 <= self.status < 600


async def _fetch(client: httpx.AsyncClient, path: str, params: dict) -> Fetch:
    headers = {"Accept": "application/json"}
    if settings().orizn_api_key:
        headers["x-api-key"] = settings().orizn_api_key
    url = f"{settings().orizn_base_url}{path}"
    try:
        r = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        log.warning("orizn %s transport error: %s", path, e)
        return Fetch(None, 0)

    # Orizn publishes the monthly allowance on every response; tracking it lets
    # the run stop itself before the quota is spent rather than after.
    try:
        remaining = int(r.headers.get("x-ratelimit-remaining", ""))
    except ValueError:
        remaining = None

    if r.status_code != 200:
        log.info("orizn %s -> HTTP %s", path, r.status_code)
        return Fetch(None, r.status_code, remaining)
    try:
        return Fetch(r.json(), 200, remaining)
    except ValueError as e:
        log.warning("orizn %s returned non-JSON: %s", path, e)
        return Fetch(None, 0, remaining)


def _verified_date(data: dict) -> date | None:
    """The publisher's own verification date, under either of its two names.

    /api/v1/visa/check returns `last_verified` as a YYYY-MM-DD date;
    /api/v1/visa returns `last_verified_at` as an ISO-8601 timestamp. Reading
    only the first is why every freshly-seeded row had a NULL verification date
    despite Orizn supplying one.
    """
    raw = data.get("last_verified") or data.get("last_verified_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
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

    # Type-guarded on purpose. Orizn's free-plan responses describe gated
    # fields with an upsell STRING ("7 documents — upgrade for full list") in
    # place of the list. Joining a string iterates its characters and would
    # store "7; ; d; o; c..." as a document checklist, so anything that is not
    # a real list is treated as absent.
    if isinstance(docs := data.get("documents_required"), list) and docs:
        chunks.append({
            "title": f"{passport} to {destination}: documents required",
            "content": "Documents required: " + "; ".join(str(d) for d in docs) + ".",
        })
    if isinstance(process := data.get("process"), list) and process:
        chunks.append({
            "title": f"{passport} to {destination}: application process",
            "content": "Application process: "
                       + " ".join(f"{i}. {s}" for i, s in enumerate(process, 1)) + ".",
        })
    validity = data.get("passport_validity_months")
    if isinstance(validity, (int, float)):
        # 0 is a real answer (the UK requires no validity beyond the stay), but
        # "valid for at least 0 months" reads as broken data, so the two cases
        # get different sentences.
        chunks.append({
            "title": f"{passport} to {destination}: passport validity",
            "content": (
                f"Passport must be valid for at least {int(validity)} months."
                if validity > 0
                else "No passport validity is required beyond the length of the stay."
            ),
        })
    fee = data.get("visa_fee") or {}
    single = (fee.get("single_entry") or {}) if isinstance(fee, dict) else {}
    if single.get("amount") is not None:
        chunks.append({
            "title": f"{passport} to {destination}: visa fee",
            "content": (
                f"Visa fee (single entry): {single.get('amount')} "
                f"{single.get('currency') or ''}".strip() + "."
            ),
        })

    insurance = data.get("insurance_required") or {}
    if isinstance(insurance, dict) and insurance.get("required"):
        amount = insurance.get("min_coverage") or insurance.get("amount")
        chunks.append({
            "title": f"{passport} to {destination}: insurance requirement",
            "content": "Travel insurance is required"
                       + (f" with minimum coverage {amount}." if amount else "."),
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


async def seed_pair(
    client: httpx.AsyncClient,
    passport: str,
    destination: str,
    prefer_full: bool = True,
) -> tuple[int, Fetch]:
    """Fetch one pair and upsert it. Returns (chunks written, last response).

    `prefer_full=False` skips straight to /check. The caller sets this once it
    has learned the key's plan does not include /visa — otherwise every
    destination would spend two requests instead of one, halving an already
    small monthly allowance.
    """
    p, d = _iso3(passport), _iso3(destination)
    params = {"passport": p, "destination": d}

    # Prefer the 30-field endpoint: /check returns only the yes/no plus upsell
    # stubs, and the documents, process and validity this pipeline is meant to
    # normalise only exist on /visa. We fall back to /check so a key without
    # the richer plan still gets the verdict.
    if prefer_full:
        path = "/api/v1/visa"
        res = await _fetch(client, path, params)
    else:
        path = "/api/v1/visa/check"
        res = await _fetch(client, path, params)
    envelope = res.data or {}
    data = envelope.get("data") or envelope

    if res.quota_exhausted or (res.transient and not data.get("requirement")):
        # No point spending a second call on the thin endpoint when the first
        # failed for quota or upstream reasons.
        return 0, res

    if prefer_full and not data.get("requirement"):
        path = "/api/v1/visa/check"
        res = await _fetch(client, path, params)
        envelope = res.data or {}
        data = envelope.get("data") or envelope

    if not data.get("requirement"):
        log.warning("no usable Orizn data for %s->%s (HTTP %s)", p, d, res.status)
        return 0, res

    # `last_verified` sits at the envelope level on /check but can ride inside
    # `data` on /visa, so look in both rather than silently losing the
    # publisher's own date — it is the only honest value for
    # source_last_verified.
    if "last_verified" not in data and envelope.get("last_verified"):
        data = {**data, "last_verified": envelope["last_verified"]}

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

        # Freshness is recorded as TWO separate facts, deliberately:
        #   fetched_at            -- when WE called Orizn. Always now().
        #   source_last_verified  -- the date ORIZN says it checked the rule.
        # Stamping now() into source_last_verified would make the UI assert
        # "Source last verified <today>" about a third party that said no such
        # thing. fetched_at is the honest freshness signal and is always set.
        now = datetime.now(timezone.utc)
        evidence.requirement = data.get("requirement")
        evidence.visa_free_days = data.get("visa_free_days")
        evidence.source_last_verified = _verified_date(data)
        evidence.orizn_payload = data
        evidence.fetched_at = now
        evidence.expires_at = now + CACHE_TTL

        await db.commit()
    log.info("seeded %s->%s with %s chunks (%s)", p, d, len(rows), path)
    return len(rows), res


async def active_destinations() -> list[str]:
    """Distinct host countries of scholarships a student could still apply to.

    This is the quota discipline: with 100 requests a month, spending them on
    a hardcoded world list would burn the allowance on countries nobody in the
    corpus can study in. "Active" mirrors the matcher's own rule — a closed
    deadline is not a destination worth a request, while rolling and
    unstated-deadline programmes are.
    """
    today = date.today()
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Scholarship.host_country_iso3)
                .where(Scholarship.host_country_iso3.is_not(None))
                .where(
                    or_(
                        Scholarship.deadline.is_(None),
                        Scholarship.is_rolling.is_(True),
                        Scholarship.deadline >= today,
                    )
                )
                .distinct()
            )
        ).scalars().all()

    # Guard against a stray code that would waste a call on a 400.
    return sorted({c.strip().upper() for c in rows if c and len(c.strip()) == 3})


async def refresh_from_corpus(
    passport: str = "PAK",
    limit: int | None = None,
    delay_seconds: float = 2.0,
) -> dict:
    """Refresh VisaEvidence for every destination in the live corpus.

    Fault tolerance, and why 429 is treated differently from 5xx:
      * 5xx / timeout  -> transient. Log and move to the next destination.
      * 429            -> the monthly allowance is gone. Every subsequent call
                          would also 429, so the run stops cleanly and reports.
                          That is still "no crash", and it protects the quota
                          far better than working through the rest of the list
                          collecting failures.

    Memory: destinations are processed one at a time and each pair is committed
    and released before the next, so peak usage does not grow with the size of
    the corpus — the whole run is a handful of dicts inside the 512MB ceiling.
    """
    p = _iso3(passport)
    # Nobody needs a visa for their own country, and the corpus does contain
    # home-country awards (HEC Overseas is host_country_iso3 = PAK). Dropping
    # it saves a request out of a 100/month allowance and avoids storing a
    # meaningless PAK->PAK row.
    destinations = [d for d in await active_destinations() if d != p]
    if limit:
        destinations = destinations[:limit]

    stats = {
        "targeted": len(destinations),
        "seeded": 0,
        "skipped": 0,
        "chunks": 0,
        "stopped_early": False,
        "remaining_quota": None,
        "failures": [],
    }
    if not destinations:
        return stats

    log.info("refreshing %s destinations: %s", len(destinations), ", ".join(destinations))

    # Learned from the first destination: if the key's plan does not include
    # the 30-field endpoint, every later destination goes straight to /check.
    prefer_full = True

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        for i, dest in enumerate(destinations):
            try:
                written, res = await seed_pair(client, passport, dest, prefer_full)
            except ValueError as e:  # non-ISO3 slipped through
                log.warning("skipping %s: %s", dest, e)
                stats["skipped"] += 1
                stats["failures"].append({"destination": dest, "reason": str(e)})
                continue
            except Exception as e:  # noqa: BLE001 - one bad pair must not end the run
                log.warning("unexpected failure for %s: %s", dest, e)
                stats["skipped"] += 1
                stats["failures"].append({"destination": dest, "reason": repr(e)})
                continue

            if res.remaining is not None:
                stats["remaining_quota"] = res.remaining

            if prefer_full and res.status in (401, 403):
                log.info("key has no /visa access; using /check for the rest")
                prefer_full = False

            if res.quota_exhausted:
                log.error(
                    "Orizn quota exhausted at %s — stopping with %s destination(s) "
                    "un-refreshed. Existing rows are left untouched.",
                    dest, len(destinations) - i,
                )
                stats["stopped_early"] = True
                stats["failures"].append({"destination": dest, "reason": "HTTP 429"})
                break

            if written:
                stats["seeded"] += 1
                stats["chunks"] += written
            else:
                stats["skipped"] += 1
                stats["failures"].append(
                    {"destination": dest, "reason": f"HTTP {res.status}"}
                )

            # Strict spacing between calls. Skipped for the final destination —
            # sleeping after the last request buys nothing but wall-clock.
            if i < len(destinations) - 1:
                await asyncio.sleep(delay_seconds)

    return stats


async def rebuild_from_payload() -> int:
    """Re-derive chunks and dates from payloads already stored. No API calls.

    The full payload is persisted on every fetch, so a parser fix — a renamed
    field, a new section — can be applied to existing rows without spending a
    single request from a 100/month allowance. Re-fetching to correct our own
    parsing would be the expensive way to fix a local bug.
    """
    rebuilt = 0
    async with SessionLocal() as db:
        rows = (await db.execute(select(VisaEvidence))).scalars().all()

        for ev in rows:
            payload = ev.orizn_payload or {}
            # Rows reconstructed by --repair-evidence hold only the verdict;
            # there is nothing to re-derive from those.
            if payload.get("reconstructed_from") or not payload.get("requirement"):
                continue

            p, d = ev.passport_iso3, ev.destination_iso3
            source_url = f"{settings().orizn_base_url}/api/v1/visa?passport={p}&destination={d}"

            await db.execute(
                delete(VisaSourceChunk).where(
                    VisaSourceChunk.passport_iso3 == p,
                    VisaSourceChunk.destination_iso3 == d,
                    VisaSourceChunk.publisher == PUBLISHER,
                )
            )
            db.add_all([VisaSourceChunk(**r) for r in _compose(p, d, payload, source_url)])
            ev.source_last_verified = _verified_date(payload)
            rebuilt += 1

        await db.commit()
    return rebuilt


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
    ap.add_argument("--rebuild-from-payload", action="store_true",
                    help="Re-derive chunks/dates from stored payloads; uses no API quota")
    ap.add_argument("--from-corpus", action="store_true",
                    help="Refresh every destination attached to an active scholarship")
    ap.add_argument("--passport", default="PAK", help="Passport ISO3 (default PAK)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap destinations this run, to protect the monthly quota")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="Seconds between Orizn calls (default 2.0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="List the targeted destinations and exit; spends no quota")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.repair_evidence:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        n = await repair_evidence()
        print(f"repaired {n} visa_evidence rows from the existing corpus")
        await engine.dispose()
        return

    if args.rebuild_from_payload:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        n = await rebuild_from_payload()
        print(f"rebuilt {n} pair(s) from stored payloads; 0 Orizn requests used")
        await engine.dispose()
        return

    if args.dry_run:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        targets = [d for d in await active_destinations()
                   if d != args.passport.strip().upper()]
        if args.limit:
            targets = targets[: args.limit]
        print(f"{len(targets)} destination(s) would be refreshed for {args.passport}:")
        print("  " + ", ".join(targets))
        print(f"  -> {len(targets)} Orizn request(s), ~{len(targets) * args.delay:.0f}s")
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

    if args.from_corpus:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        stats = await refresh_from_corpus(
            passport=args.passport, limit=args.limit, delay_seconds=args.delay
        )
        print(
            f"targeted {stats['targeted']} | seeded {stats['seeded']} | "
            f"skipped {stats['skipped']} | chunks {stats['chunks']}"
        )
        if stats["remaining_quota"] is not None:
            print(f"orizn quota remaining: {stats['remaining_quota']}")
        if stats["stopped_early"]:
            print("STOPPED EARLY: monthly quota exhausted. Re-run after it resets.")
        for f in stats["failures"]:
            print(f"  skipped {f['destination']}: {f['reason']}")
        await engine.dispose()
        return

    pairs = ([tuple(p.upper().split(":", 1)) for p in args.pair] if args.pair
             else DEFAULT_PAIRS)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    total = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        for passport, destination in pairs:
            written, _ = await seed_pair(client, passport, destination)
            total += written
            await asyncio.sleep(2.0)  # strict spacing; the quota is small

    async with SessionLocal() as db:
        corpus = len((await db.execute(select(VisaSourceChunk.id))).all())
    print(f"wrote {total} chunks; {corpus} total in visa_source_chunks")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
