"""Playwright crawlers for the Erasmus Mundus catalogue and the DAAD database.

Both targets are JavaScript-rendered, so the HTTP tier in crawler.py cannot
see them -- this is the escalation path that module was built for.

Memory discipline (the 512MB ceiling)
-------------------------------------
Chromium is the single largest thing this project ever runs, so the crawl is
deliberately boring:

  * ONE browser, ONE page, reused for every URL. A page-per-URL pattern is what
    makes headless crawls balloon; tabs are not free.
  * images, fonts, media and stylesheets are aborted at the network layer. We
    are reading text, and the decoded bitmaps are the bulk of a browser's RSS.
  * Records are flushed to Postgres in small batches and dropped, so peak
    memory does not grow with catalogue size. Crawling 200 programmes costs
    roughly the same as crawling 20.
  * Strictly serial. Concurrency here would multiply the browser's memory by
    the worker count for no wall-clock benefit on a rate-limited public site.

This runs in the ingest image (Dockerfile.ingest), never in the API container.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from datetime import date, datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from ..db import Base, SessionLocal, engine
from ..models import Scholarship

log = logging.getLogger(__name__)

UA = "ScholarCompassBot/0.1 (+https://scholarcompass.app/bot; contact: info@genetechsol.com)"
BLOCKED_RESOURCES = {"image", "font", "media", "stylesheet"}
FLUSH_EVERY = 20
NAV_TIMEOUT = 30_000

ERASMUS_BASE = "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en"
DAAD_BASE = "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/"

# DAAD dropdown values, read from the live <select id="s-status"> options.
DAAD_STATUS = {"bachelor": "1", "master": "3", "phd": "4"}


def _slug(prefix: str, key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{prefix}-{key}".lower()).strip("-")[:200]


async def _upsert(rows: list[dict]) -> int:
    """Idempotent by slug, so re-crawling refreshes rather than duplicates."""
    if not rows:
        return 0
    async with SessionLocal() as db:
        stmt = insert(Scholarship).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Scholarship.slug],
            set_={k: getattr(stmt.excluded, k) for k in rows[0] if k not in ("id", "slug")},
        )
        await db.execute(stmt)
        await db.commit()
    return len(rows)


# --- deadline parsing ------------------------------------------------------

_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_DATE_PATTERNS = (
    r"(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})",
    r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})",
    r"(\d{1,2})[./](\d{1,2})[./](\d{4})",
)


def parse_deadline(text: str) -> date | None:
    """Pull an application deadline out of prose.

    Returns None rather than guessing. A wrong deadline is worse than a missing
    one: the matcher would either hide a live opportunity or present a dead one
    as open, and both are exactly what the R0-R5 rules exist to prevent.
    """
    if not text:
        return None
    window = text[:12000].lower()
    idx = window.find("application deadline")
    if idx == -1:
        idx = window.find("deadline")
    if idx == -1:
        return None

    # Some publishers state a policy instead of a date. DAAD, for example, says
    # "Application deadlines are updated annually in the second quarter" and
    # never prints a calendar date. Extracting some other date from that
    # sentence would invent a deadline, so bail out explicitly.
    if re.search(r"deadlines?\s+are\s+updated\s+annually|updated\s+annually", window):
        return None

    # Only look just after the word, so an unrelated date elsewhere on a long
    # page cannot be mistaken for the deadline.
    near = window[idx : idx + 220]

    for pattern in _DATE_PATTERNS:
        m = re.search(pattern, near)
        if not m:
            continue
        try:
            g = m.groups()
            if g[1] in _MONTHS:
                return date(int(g[2]), _MONTHS.index(g[1]) + 1, int(g[0]))
            if g[0] in _MONTHS:
                return date(int(g[2]), _MONTHS.index(g[0]) + 1, int(g[1]))
            return date(int(g[2]), int(g[1]), int(g[0]))
        except (ValueError, IndexError):
            continue
    return None


# --- browser plumbing ------------------------------------------------------

class Crawler:
    """One browser, one page, reused. See the memory notes at module top."""

    def __init__(self, headless: bool = True):
        self.headless = headless

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=self.headless,
            # /dev/shm is tiny in containers; without this Chromium crashes
            # rather than degrading.
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
        )
        self.ctx = await self.browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        await self.ctx.route("**/*", self._filter)
        self.page = await self.ctx.new_page()
        self.page.set_default_navigation_timeout(NAV_TIMEOUT)
        return self

    async def __aexit__(self, *exc):
        await self.ctx.close()
        await self.browser.close()
        await self._pw.stop()

    @staticmethod
    async def _filter(route):
        if route.request.resource_type in BLOCKED_RESOURCES:
            await route.abort()
        else:
            await route.continue_()

    async def goto(self, url: str) -> bool:
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            return True
        except Exception as e:  # noqa: BLE001 - one bad page must not end the crawl
            log.warning("navigation failed %s: %s", url, e)
            return False

    async def dismiss_cookies(self) -> None:
        """DAAD's consent banner owns the <h1> until it is dismissed."""
        for selector in (
            "button.snoop-button--primary",
            "a#accept",
            "button:has-text('ACCEPT')",
        ):
            try:
                el = self.page.locator(selector).first
                if await el.is_visible(timeout=1200):
                    await el.click(timeout=2000)
                    await self.page.wait_for_timeout(250)
                    return
            except Exception:  # noqa: BLE001 - no banner is the happy path
                continue


# --- Erasmus Mundus --------------------------------------------------------

ERASMUS_JS = """() => [...document.querySelectorAll('.ecl-card')].map(card => {
  const a = card.querySelector('.ecl-content-block__title a');
  const desc = card.querySelector('.ecl-content-block__description');
  return {
    title: a ? a.innerText.trim() : null,
    url: a ? a.href : null,
    description: desc ? desc.innerText.trim() : ''
  };
}).filter(x => x.title && x.url)"""


async def crawl_erasmus(c: Crawler, max_pages: int = 11) -> int:
    """Erasmus Mundus joint masters. The card title links straight to the
    programme's own site, which is the page a student actually applies on --
    so it becomes source_url and powers the results-page redirect."""
    total, batch = 0, []

    for page_no in range(max_pages):
        url = f"{ERASMUS_BASE}?page={page_no}"
        if not await c.goto(url):
            continue
        try:
            await c.page.wait_for_selector(".ecl-card", timeout=8000)
        except Exception:  # noqa: BLE001
            log.info("no cards on erasmus page %s; stopping", page_no)
            break

        cards = await c.page.evaluate(ERASMUS_JS)
        if not cards:
            break

        for card in cards:
            batch.append({
                "slug": _slug("erasmus-mundus", card["url"]),
                "title": card["title"][:500],
                "provider": "Erasmus Mundus (European Commission)",
                "host_country_iso3": None,  # joint programmes span several countries
                "degree_levels": ["master"],
                "fields_of_study": [],
                "min_gpa_4": None,
                "min_language_score": {},
                "eligible_nationalities": [],
                "excluded_nationalities": [],
                "max_age": None,
                "funding_type": "full",
                "deadline": None,  # stated per-consortium, not in the catalogue
                "is_rolling": False,
                "source_url": card["url"],
                "last_verified_at": datetime.now(timezone.utc),
                "fetch_strategy": "playwright",
                "raw": {"catalogue_description": card["description"][:1000],
                        "catalogue_page": page_no},
            })

        log.info("erasmus page %s -> %s programmes", page_no, len(cards))
        if len(batch) >= FLUSH_EVERY:
            total += await _upsert(batch)
            batch = []  # drop immediately; peak memory must not track catalogue size

    total += await _upsert(batch)
    return total


# --- DAAD ------------------------------------------------------------------

DAAD_IDS_JS = """() => {
  const ids = new Set();
  document.querySelectorAll('a[href*="detail="]').forEach(a => {
    const m = a.href.match(/detail=(\\d+)/);
    if (m && a.innerText.trim().length > 5) ids.add(m[1]);
  });
  return [...ids];
}"""

DAAD_DETAIL_JS = """() => {
  const main = document.querySelector('#content, main, .c-detail') || document.body;
  // NOT <h1>: on a DAAD detail page the h1 is the section heading
  // ("Finding Scholarships"), identical on every programme. document.title
  // carries the actual programme name, suffixed with the site name.
  const title = (document.title || '')
      .replace(/\\s*[-–|]\\s*DAAD.*$/i, '')
      .replace(/\\s*•\\s*DAAD\\s*$/i, '')
      .trim();
  // textContent, NOT innerText: DAAD splits each programme across tab panels
  // (Overview / Requirements / Procedure / Submitting an application) and the
  // inactive ones are display:none. innerText silently drops those.
  const text = (main.textContent || '').replace(/\\s+/g, ' ').trim();
  return { title: title || null, text: text.slice(0, 12000) };
}"""


async def crawl_daad(c: Crawler, origin: str = "194", status: str = "3", limit: int = 30) -> int:
    """DAAD scholarship database, driven through its dynamic dropdowns.

    `origin` is the applicant's country of residence (194 = Pakistan) and
    `status` the degree stage (3 = Graduates) -- both read from the live
    <select> options rather than hardcoded from memory. Filtering by origin
    matters: DAAD genuinely varies eligibility by nationality, so a catalogue
    scraped without it would list programmes a Pakistani student cannot apply
    for, which is exactly the false-hope failure R0 is meant to prevent.
    """
    listing = (f"{DAAD_BASE}?status={status}&origin={origin}&subjectGrps=&daad="
               f"&intention=&q=&page=1&lang=en&sd=1")
    if not await c.goto(listing):
        return 0
    await c.dismiss_cookies()
    await c.page.wait_for_timeout(600)

    ids = await c.page.evaluate(DAAD_IDS_JS)
    log.info("daad listing (origin=%s status=%s) -> %s programmes", origin, status, len(ids))
    ids = ids[:limit]

    total, batch = 0, []
    for i, pid in enumerate(ids, 1):
        detail_url = f"{DAAD_BASE}?detail={pid}"
        if not await c.goto(detail_url):
            continue
        try:
            await c.page.wait_for_selector("h1", timeout=6000)
        except Exception:  # noqa: BLE001
            pass

        data = await c.page.evaluate(DAAD_DETAIL_JS)
        if not data or not data.get("title"):
            log.info("daad %s: no title, skipping", pid)
            continue

        text = data["text"] or ""
        level = next((k for k, v in DAAD_STATUS.items() if v == status), "master")
        batch.append({
            "slug": _slug("daad", pid),
            "title": data["title"][:500],
            "provider": "DAAD",
            "host_country_iso3": "DEU",
            "degree_levels": [level],
            "fields_of_study": [],
            "min_gpa_4": None,
            "min_language_score": {},
            # The listing was filtered by origin, so every row here is one this
            # nationality may apply for. Recorded as provenance, not as a claim.
            "eligible_nationalities": [],
            "excluded_nationalities": [],
            "max_age": None,
            "funding_type": "full",
            "deadline": parse_deadline(text),
            "is_rolling": False,
            "source_url": detail_url,
            "last_verified_at": datetime.now(timezone.utc),
            "fetch_strategy": "playwright",
            "raw": {"daad_id": pid, "filtered_by_origin": origin,
                    "excerpt": text[:1500],
                    # DAAD publishes a policy, not a date. Recording that
                    # distinction lets the UI say "announced annually — check
                    # the official page" instead of the ambiguous
                    # "deadline not stated".
                    "deadline_note": ("Deadlines are updated annually; check the "
                                      "official page for this cycle's date.")
                    if re.search(r"updated annually", text, re.I) else None},
        })

        if len(batch) >= FLUSH_EVERY:
            total += await _upsert(batch)
            batch = []
        # Deliberate politeness gap on a public, non-commercial service.
        await c.page.wait_for_timeout(400)
        if i % 10 == 0:
            log.info("daad %s/%s", i, len(ids))

    total += await _upsert(batch)
    return total


async def main() -> None:
    ap = argparse.ArgumentParser(description="Crawl Erasmus Mundus and DAAD catalogues")
    ap.add_argument("--erasmus", action="store_true")
    ap.add_argument("--daad", action="store_true")
    ap.add_argument("--origin", default="194", help="DAAD country id (194 = Pakistan)")
    ap.add_argument("--status", default="3", help="DAAD status id (3 = Graduates)")
    ap.add_argument("--max-pages", type=int, default=11)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    written = 0
    async with Crawler(headless=not args.headful) as c:
        if args.erasmus or not args.daad:
            written += await crawl_erasmus(c, max_pages=args.max_pages)
        if args.daad or not args.erasmus:
            written += await crawl_daad(c, origin=args.origin, status=args.status,
                                        limit=args.limit)

    print(f"wrote {written} scholarship rows")
    await engine.dispose()


def _demo() -> None:
    """Self-check for deadline parsing -- no browser, no network."""
    assert parse_deadline("Application deadline: 15 October 2027") == date(2027, 10, 15)
    assert parse_deadline("The application deadline is October 15, 2027") == date(2027, 10, 15)
    assert parse_deadline("Deadline 01.03.2027") == date(2027, 3, 1)
    # A date far from the word "deadline" must not be captured.
    assert parse_deadline("Published 3 May 2020. " + "x" * 500 + " deadline unknown") is None
    # No deadline at all -> None, never a guess.
    assert parse_deadline("Funding covers tuition and travel.") is None
    assert parse_deadline("") is None
    # Garbage dates must not raise.
    assert parse_deadline("Application deadline: 99 Foobuary 2027") is None
    # A stated POLICY is not a date. This is DAAD's real wording, and the 2025
    # in it must not be harvested as a deadline.
    assert parse_deadline(
        "Application Procedure Application deadline Application deadlines are "
        "updated annually in the second quarter. In most cases they match 2025."
    ) is None
    print("catalogue deadline-parsing self-check passed")


if __name__ == "__main__":
    if "--selfcheck" in __import__("sys").argv:
        _demo()
    else:
        asyncio.run(main())
