"""Crawl runner. Entrypoint of the ingest image.

    python -m app.ingest.run --url https://example.edu/scholarship
    python -m app.ingest.run --seed        # load the local demo corpus

Extraction is LLM-assisted but the RESULT is deterministic data: every field
the matcher filters on lands in a typed column, so matching never asks a model
"is this student eligible?". The model's only job is reading prose into fields.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db import SessionLocal, engine
from ..db import Base
from ..llm import complete_json
from ..models import Scholarship
from .crawler import fetch, visible_text

log = logging.getLogger(__name__)

EXTRACT_SYSTEM = """You read scholarship pages and return structured JSON.

Return exactly these keys:
  title, provider, host_country_iso3, degree_levels (array of
  bachelor|master|phd|postdoc), fields_of_study (array of short lowercase
  tags), min_gpa_4 (number 0-4 or null), min_language_score (object like
  {"ielts":6.5} or {}), eligible_nationalities (array of ISO3; EMPTY array
  means open to all), excluded_nationalities (array of ISO3), max_age (int or
  null), funding_type (full|partial|tuition|null), deadline (YYYY-MM-DD or
  null), is_rolling (bool).

Rules:
- Use null when the page does not say. Never invent a cutoff.
- Do not convert grades. If a GPA is stated on a non-4.0 scale, return null.
- eligible_nationalities is for explicit restrictions only. A page that merely
  mentions a country in passing is NOT a restriction."""


def _slug(url: str, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{title}-{url}".lower()).strip("-")
    return base[:200]


async def _upsert(rows: list[dict]) -> int:
    """Idempotent by slug -- re-crawling a page updates it, never duplicates."""
    if not rows:
        return 0
    async with SessionLocal() as db:
        stmt = insert(Scholarship).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Scholarship.slug],
            set_={
                k: getattr(stmt.excluded, k)
                for k in rows[0]
                if k not in ("id", "slug")
            },
        )
        await db.execute(stmt)
        await db.commit()
    return len(rows)


async def crawl(urls: list[str]) -> int:
    total = 0
    for url in urls:
        try:
            page = await fetch(url)
        except Exception as e:  # noqa: BLE001 - one bad host must not stop a run
            log.warning("fetch failed %s: %s", url, e)
            continue

        text = visible_text(page.html)[:12000]
        if len(text) < 200:
            log.warning("no usable content at %s (strategy=%s)", url, page.strategy)
            continue

        data = await complete_json(EXTRACT_SYSTEM, f"URL: {page.url}\n\n{text}")
        if not data or not data.get("title"):
            log.warning("extraction produced nothing for %s", url)
            continue

        data = _coerce(data)
        data.update(
            slug=_slug(page.url, data["title"]),
            source_url=page.url,
            last_verified_at=datetime.now(timezone.utc),
            fetch_strategy=page.strategy,
            content_hash=page.content_hash,
        )
        total += await _upsert([data])
        log.info("ingested %s via %s", data["title"], page.strategy)
    return total


_ALLOWED = {
    "title", "provider", "host_country_iso3", "degree_levels", "fields_of_study",
    "min_gpa_4", "min_language_score", "eligible_nationalities",
    "excluded_nationalities", "max_age", "funding_type", "deadline", "is_rolling",
    "raw",
}


def _coerce(d: dict) -> dict:
    """Drop unknown keys and repair the types models get wrong."""
    out = {k: v for k, v in d.items() if k in _ALLOWED}
    out.setdefault("raw", {})
    for k in ("degree_levels", "fields_of_study", "eligible_nationalities",
              "excluded_nationalities"):
        v = out.get(k)
        out[k] = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
    for k in ("eligible_nationalities", "excluded_nationalities", "host_country_iso3"):
        v = out.get(k)
        if isinstance(v, list):
            out[k] = [x.upper()[:3] for x in v]
        elif isinstance(v, str):
            out[k] = v.upper()[:3]
    if isinstance(out.get("deadline"), str):
        try:
            out["deadline"] = datetime.strptime(out["deadline"][:10], "%Y-%m-%d").date()
        except ValueError:
            out["deadline"] = None
    gpa = out.get("min_gpa_4")
    # A model that ignored the instruction and returned a 10-point CGPA would
    # otherwise become an impossible cutoff that rejects everyone.
    out["min_gpa_4"] = gpa if isinstance(gpa, (int, float)) and 0 <= gpa <= 4 else None
    out.setdefault("min_language_score", {})
    out.setdefault("is_rolling", False)
    return out


async def seed() -> int:
    path = pathlib.Path(__file__).parent / "seed.json"
    rows = [_coerce(r) | {"slug": r["slug"], "source_url": r["source_url"],
                          "last_verified_at": datetime.now(timezone.utc),
                          "fetch_strategy": "seed"}
            for r in json.loads(path.read_text(encoding="utf-8"))]
    return await _upsert(rows)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--seed", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    n = await seed() if args.seed else await crawl(args.url)
    async with SessionLocal() as db:
        total = len((await db.execute(select(Scholarship.id))).all())
    print(f"wrote {n} rows; {total} scholarships in database")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
