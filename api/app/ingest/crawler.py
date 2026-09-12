"""Two-tier fetch: cheap HTTP first, headless browser only when forced.

Most scholarship pages are server-rendered HTML and a plain GET is enough.
A minority (increasingly, university portals behind React/Angular front ends)
return a near-empty shell and paint the eligibility criteria from JSON after
hydration. Those are precisely the pages whose deadlines and GPA cutoffs we
cannot afford to miss, so they get a real browser.

Playwright is deliberately NOT a dependency of the API image. Chromium plus
Playwright is ~400MB installed, which does not fit beside FastAPI in a 512MB
container. It lives in a separate ingest image (Dockerfile.ingest) that runs
as a scheduled job, and is imported lazily here so importing this module from
the API never requires it.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

UA = "ScholarCompassBot/0.1 (+https://scholarcompass.app/bot; contact: info@genetechsol.com)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Below this much visible text, a 200 OK is almost certainly an empty SPA shell.
MIN_TEXT_CHARS = 600

_SPA_MARKERS = (
    'id="__next"',
    'id="root"',
    "ng-version",
    "data-reactroot",
    "__NUXT__",
)
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ANGLE_RE = re.compile(r"<[^>]+>")


@dataclass
class Fetched:
    url: str
    html: str
    strategy: str  # "http" | "playwright"
    status: int
    content_hash: str


def visible_text(html: str) -> str:
    """Rough text extraction -- enough to judge whether a page has content."""
    stripped = _TAG_RE.sub(" ", html)
    return re.sub(r"\s+", " ", _ANGLE_RE.sub(" ", stripped)).strip()


def needs_js(html: str) -> bool:
    """Decide whether a headless browser is worth the ~2s and the memory.

    Checks content first and framework markers second: a server-rendered
    Next.js page still carries `id="__next"` but has plenty of text, and
    re-fetching it in a browser would be pure waste.
    """
    if len(visible_text(html)) >= MIN_TEXT_CHARS:
        return False
    return any(m in html for m in _SPA_MARKERS) or len(visible_text(html)) < 200


async def _fetch_http(url: str) -> Fetched:
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        r = await client.get(url)
        return Fetched(
            url=str(r.url),
            html=r.text,
            strategy="http",
            status=r.status_code,
            content_hash=hashlib.sha256(r.text.encode("utf-8", "ignore")).hexdigest(),
        )


async def _fetch_playwright(url: str) -> Fetched:
    # Imported here, not at module scope, so the API image never needs it.
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        try:
            ctx = await browser.new_context(user_agent=UA)
            # Images and fonts are pure cost for a text scrape; blocking them
            # cuts both wall-clock and the browser's memory footprint.
            await ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_(),
            )
            page = await ctx.new_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # networkidle is unreliable on pages with polling/analytics, so we
            # wait for actual text instead of an arbitrary sleep.
            try:
                await page.wait_for_function(
                    f"document.body && document.body.innerText.length > {MIN_TEXT_CHARS}",
                    timeout=8000,
                )
            except Exception:  # noqa: BLE001 - take whatever rendered by now
                log.info("js render timed out waiting for text: %s", url)
            html = await page.content()
            return Fetched(
                url=page.url,
                html=html,
                strategy="playwright",
                status=resp.status if resp else 0,
                content_hash=hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest(),
            )
        finally:
            await browser.close()


async def fetch(url: str, allow_js: bool = True) -> Fetched:
    """Fetch a page, escalating to a headless browser only if HTML is empty."""
    result = await _fetch_http(url)
    if not allow_js or not needs_js(result.html):
        return result

    log.info("escalating to headless browser: %s", url)
    try:
        return await _fetch_playwright(url)
    except ImportError:
        # Running inside the API image, which has no Playwright. Degrade to the
        # thin HTML rather than failing the crawl outright.
        log.warning("playwright unavailable; keeping http result for %s", url)
        return result


def _demo() -> None:
    """Self-check for the escalation heuristic -- no network, no browser."""
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    assert needs_js(shell), "empty SPA shell must escalate"

    # Server-rendered Next.js: has the marker, but also has real content.
    rendered = (
        '<html><body><div id="__next"><article>'
        + ("Eligibility: applicants must hold a bachelor degree. " * 30)
        + "</article></div></body></html>"
    )
    assert not needs_js(rendered), "server-rendered page must not waste a browser"

    # Script-heavy but text-light: still a shell.
    noisy = "<html><body>" + ("<script>var x=1;</script>" * 200) + "Loading...</body></html>"
    assert needs_js(noisy), "script bulk must not count as content"

    assert len(visible_text("<p>hello <b>world</b></p>")) == len("hello world")
    print("crawler heuristic self-check passed")


if __name__ == "__main__":
    _demo()
