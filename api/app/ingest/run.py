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

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..db import SessionLocal, engine
from ..db import Base
from ..llm import complete_json
from ..models import Scholarship
from ..profile_extract import FIELD_TAGS
from .catalogue import infer_fields
from .crawler import fetch, visible_text

log = logging.getLogger(__name__)

EXTRACT_SYSTEM = """You read scholarship pages and return structured JSON.

Return exactly these keys:
  title, provider, host_country_iso3, degree_levels (array of
  bachelor|master|phd|postdoc), fields_of_study (array chosen ONLY from the
  canonical list given below — free-form tags are discarded),
  min_gpa_4 (number 0-4 or null), min_language_score (object like
  {"ielts":6.5} or {}), eligible_nationalities (array of ISO3; EMPTY array
  means open to all), excluded_nationalities (array of ISO3), max_age (int or
  null), funding_type (full|partial|tuition|null), deadline (YYYY-MM-DD or
  null), is_rolling (bool),
  min_work_experience_hours (int or null — ONLY if the page prints a specific
    number of HOURS. Never convert from years, never estimate),
  return_obligation (string or null — a requirement to return to or reside in
    the home country after the award, quoted briefly),
  entry_requirement (string or null — the prior-degree requirement in the
    page's own words, e.g. "a bachelor's degree or equivalent").

Rules:
- Use null when the page does not say. Never invent a cutoff.
- Do not convert grades. If a GPA is stated on a non-4.0 scale, return null.
- eligible_nationalities is for explicit restrictions only. A page that merely
  mentions a country in passing is NOT a restriction.

CANONICAL fields_of_study — use these exact strings and nothing else:
engineering, computer science, medicine, economics, public policy,
agriculture, environment, law, physics, chemistry, biology,
arts and humanities, education, social sciences, mathematics"""


def _domain_of(url: str) -> str | None:
    """Bare registrable-ish host, for the logo CDN. `www.` stripped."""
    m = re.match(r"https?://([^/:?#]+)", url or "")
    return m.group(1).lower().removeprefix("www.") if m else None


def _slug(url: str, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{title}-{url}".lower()).strip("-")
    return base[:200]


async def _upsert(rows: list[dict], merge: bool = False) -> int:
    """Idempotent by slug -- re-crawling a page updates it, never duplicates.

    `merge=True` keeps an existing non-null value when the incoming one is
    null. Flagship programmes are documented across several pages (Chevening
    prints its 2,800 hours on one page and its return obligation on another),
    so the pages must accumulate into one row instead of overwriting each
    other with whichever page was crawled last -- or, worse, appearing as three
    separate Chevening scholarships in the results.
    """
    if not rows:
        return 0
    async with SessionLocal() as db:
        stmt = insert(Scholarship).values(rows)
        cols = [k for k in rows[0] if k not in ("id", "slug")]
        set_ = {
            k: (func.coalesce(getattr(stmt.excluded, k), getattr(Scholarship, k))
                if merge else getattr(stmt.excluded, k))
            for k in cols
        }
        stmt = stmt.on_conflict_do_update(index_elements=[Scholarship.slug], set_=set_)
        await db.execute(stmt)
        await db.commit()
    return len(rows)


async def crawl(
    urls: list[str],
    domains: dict[str, str] | None = None,
    keys: dict[str, str] | None = None,
) -> int:
    """Serial on purpose -- see catalogue.py. One browser, one page at a time."""
    total = 0
    domains = domains or {}
    keys = keys or {}
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

        data = _coerce(data, title_hint=str(data.get("title") or ""), source_text=text)
        data.update(
            slug=keys.get(url) or _slug(page.url, data["title"]),
            source_url=page.url,
            last_verified_at=datetime.now(timezone.utc),
            fetch_strategy=page.strategy,
            content_hash=page.content_hash,
            provider_domain=domains.get(url) or _domain_of(page.url),
        )
        total += await _upsert([data], merge=bool(keys))
        log.info("ingested %s via %s", data["title"], page.strategy)
    return total


_ALLOWED = {
    "title", "provider", "host_country_iso3", "degree_levels", "fields_of_study",
    "min_gpa_4", "min_language_score", "eligible_nationalities",
    "excluded_nationalities", "max_age", "funding_type", "deadline", "is_rolling",
    "min_work_experience_hours", "return_obligation", "entry_requirement",
    "provider_domain", "raw",
}

# Flagship programmes, with the domain used to hotlink a provider logo.
# Hand-curated because a logo pointing at the wrong brand is worse than no
# logo, and domain guessing from a page URL gets CDN and redirect hosts wrong.
FLAGSHIP = [
    # (url, logo domain, programme key). The key is the slug, so several pages
    # documenting ONE programme merge into one row instead of appearing as
    # three separate Chevening scholarships.
    #
    # Chevening: the work-experience page, NOT /scholarship/eligibility/ --
    # the latter is a JS shell whose fetched text contains none of the actual
    # figures, and asking a model to extract from it produced invented ones.
    ("https://www.chevening.org/scholarship/eligibility/work-experience/",
     "chevening.org", "flagship-chevening"),
    ("https://www.chevening.org/faqs/", "chevening.org", "flagship-chevening"),
    ("https://foreign.fulbrightonline.org/about/foreign-fulbright",
     "fulbrightonline.org", "flagship-fulbright"),
    ("https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program",
     "campusfrance.org", "flagship-eiffel"),
    ("https://www.studyinjapan.go.jp/en/planning/scholarship/",
     "studyinjapan.go.jp", "flagship-mext"),
    # campuschina.org answers 412 to non-browser clients and its JS render
    # times out; left here so the gap stays visible rather than quietly dropped.
    ("https://www.campuschina.org/scholarships/index.html",
     "campuschina.org", "flagship-csc"),
]


def _grounded(value: int | None, source_text: str) -> int | None:
    """Keep a numeric claim only if that number appears in the page.

    This exists because of a real failure: asked about Chevening, the model
    returned 5,400 work hours and a max age of 30 from a page containing
    neither figure. Both are wrong (Chevening publishes 2,800 hours and has no
    age limit), and both would have been shown to students as fact.

    A plausible invented number is worse than a missing one -- a student can
    act on it. So any figure we cannot find in the source is dropped, and the
    field falls back to "not stated", which the matcher already treats as
    "do not filter".
    """
    if value is None:
        return None
    haystack = source_text.replace(",", "").replace(" ", "")
    return value if str(int(value)) in haystack else None


def _coerce(d: dict, title_hint: str = "", source_text: str = "") -> dict:
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

    hours = out.get("min_work_experience_hours")
    # Bounded to something a human could plausibly have worked. A model that
    # misreads "2,800 hours" as "2800 years" would otherwise create a gate no
    # applicant on earth clears, silently hiding the scholarship from everyone.
    out["min_work_experience_hours"] = _grounded(
        int(hours) if isinstance(hours, (int, float)) and 0 < hours <= 100_000 else None,
        source_text,
    )
    age = out.get("max_age")
    out["max_age"] = _grounded(
        int(age) if isinstance(age, (int, float)) and 10 < age <= 99 else None,
        source_text,
    )
    for key in ("return_obligation", "entry_requirement"):
        v = out.get(key)
        out[key] = str(v).strip()[:400] if isinstance(v, str) and v.strip() else None

    # Enforce the canonical field vocabulary in code, not just in the prompt.
    # A model that returns "peace" or "entrepreneurship" is not wrong about the
    # page -- it is just using words the matcher's filter cannot compare
    # against, which silently demotes the scholarship to R5 for everyone.
    canon = set(FIELD_TAGS)
    tags = [t.lower() for t in out.get("fields_of_study", []) if t.lower() in canon]
    if not tags:
        # Fall back to the same deterministic tagger the catalogue crawlers use.
        tags = infer_fields(title_hint or str(out.get("title") or ""))
    out["fields_of_study"] = tags[:4]
    return out


async def seed() -> int:
    path = pathlib.Path(__file__).parent / "seed.json"
    # Seed rows are hand-written and trusted, so they are grounded against
    # themselves -- the check exists to catch a model inventing figures, not to
    # second-guess curated fixtures.
    rows = [_coerce(r, source_text=json.dumps(r)) | {"slug": r["slug"], "source_url": r["source_url"],
                          "last_verified_at": datetime.now(timezone.utc),
                          "fetch_strategy": "seed"}
            for r in json.loads(path.read_text(encoding="utf-8"))]
    return await _upsert(rows)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--flagship", action="store_true",
                    help="Crawl the curated flagship programmes with logo domains")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if args.seed:
        n = await seed()
    elif args.flagship:
        n = await crawl(
            [u for u, _, _ in FLAGSHIP],
            {u: d for u, d, _ in FLAGSHIP},
            {u: k for u, _, k in FLAGSHIP},
        )
    else:
        n = await crawl(args.url)
    async with SessionLocal() as db:
        total = len((await db.execute(select(Scholarship.id))).all())
    print(f"wrote {n} rows; {total} scholarships in database")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
