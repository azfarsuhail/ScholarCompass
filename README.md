# ScholarCompass

Scholarship and visa discovery with no accounts. Hard deterministic eligibility
filtering first, an LLM for semantic fit second, and a separate citation-bound
RAG pipeline for visa requirements.

```
web/   Next.js 16 App Router · Motion · Tailwind v4   → Vercel
api/   FastAPI · SQLAlchemy 2.0 · Neon Postgres       → 512MB container
```

## The one idea

Eligibility is a database question with a right answer. Fit is a judgement
call. Only the second one gets a model.

If a scholarship's rules bar you, no amount of AI enthusiasm puts it on your
screen. Everything the LLM produces is *additive*: with no `GROQ_API_KEY` set
you still get complete, ranked, explained results — just without the prose.

## Run it

```bash
docker compose up -d db
cd api && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/scholarcompass \
  .venv/Scripts/python -m app.ingest.run --seed
DATABASE_URL=... SESSION_SECRET=... COOKIE_SECURE=false \
  .venv/Scripts/python -m uvicorn app.main:app --port 8000

cd web && API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

```bash
cd api && .venv/Scripts/python -m pytest        # 58 tests
.venv/Scripts/python -m pytest -m live          # hits real Orizn; needs a key
```

## Decisions worth knowing

**The API is proxied same-origin.** `next.config.ts` rewrites `/api/*` to the
backend. This is not tidiness — the session cookie is `HttpOnly; SameSite=Lax`,
and browsers do not send Lax cookies on cross-site fetches. Point the browser
straight at another domain and every request mints a fresh empty session.
Chosen over `SameSite=None` because it keeps the cookie first-party and removes
the need for CORS entirely.

**`VisaEvidence` is not session-scoped.** A passport+destination pair attached
to a session id is a travel-intent record about a person. The same pair alone
is public reference data. Keeping it global caches better *and* deletes the
only row that could profile a student.

**Grade conversion is per-country and piecewise.** `percentage / 100 * 4` is
wrong in the direction that hurts students: 62% is a First Division in Pakistan
(~3.3) and a D in the US (~1.0), and German grades run backwards (1.0 best), so
a linear map inverts the ranking. Every conversion carries a confidence, and
low-confidence OCR GPAs get tolerance at R0 so a scan artefact cannot silently
hide an eligible scholarship.

**RAG answers without resolvable citations are discarded.** Not flagged —
dropped. A student can act on an uncited visa instruction and lose a fee or a
semester.

**512MB shapes the dependency list.** No torch: OCR is Tesseract, and retrieval
is Postgres full-text search rather than embeddings (Groq has no embeddings
endpoint, and this corpus is full of exact terms like "JW202" where lexical
search is genuinely strong). Playwright lives in a separate ingest image —
~400MB with Chromium, for a capability no request path uses. One uvicorn
worker; scale with containers, not workers.

## R0–R5

| Rung | Relaxes | Shown as |
|------|---------|----------|
| R0 | nothing | Exact match |
| R1 | funding type | Partial funding |
| R2 | language minimum | Needs a test score |
| R3 | GPA, by 0.3 | Slightly above your GPA |
| R4 | deadline, within 12 months | Closed — next cycle |
| R5 | field of study | Outside your field |

Ordered by how much the student would have to change. GPA relaxes before
deadline because a near miss that is still open beats a perfect fit that
closed last month.

**Never relaxed, at any rung**, including R5: nationality exclusions and
whitelists, and degree level. Closed deadlines appear only at R4 and are always
labelled closed.

The ladder runs in memory over one coarse SQL query rather than six round-trips
to Neon — measured 1.7s against Neon in ap-southeast-1, well inside the 5s budget. It is a pure function over
plain dicts, so it is tested without a database.

## Privacy

No accounts. A signed `HttpOnly` cookie carries an opaque session UUID and
nothing else. Uploads are OCR'd and discarded — only the extracted grade is
kept. A background sweeper hard-deletes expired sessions, and `DELETE
/v1/session` erases everything immediately.

Verified: forged cookies are rejected and re-issued, and after deletion the old
cookie resolves to a brand-new empty session.

## The funnel

```
/          landing
/start     details (transcript upload or manual)
/results   progressive matches -> direct handoff to the official application page
```

Each result card links straight to the programme's own site — the Erasmus
catalogue's title link *is* the application URL. No intermediate detail page,
no affiliate hop. It opens in a new tab so a student does not lose their
results on every outbound click.

## Data

237 programmes crawled live from the Erasmus Mundus catalogue and the DAAD
database (driven through its real dropdowns: `origin=194` Pakistan,
`status=3` Graduates, read from the live `<select>`).

Crawling is strictly serial with one reused browser page and images/fonts/media
blocked at the network layer, so peak memory does not track catalogue size.
Playwright lives only in `Dockerfile.ingest`.

`visa_source_chunks` is seeded from Orizn rather than scraped from government
portals. Catalogue text never enters the visa corpus — otherwise "what visa do
I need?" could retrieve a scholarship deadline.

## Validation

`passport=PAK&destination=CHN` returns `visa_required`, plus a RAG explanation
whose citations all resolve to real Orizn URLs. Verified end to end against
live Neon, Orizn and Groq:

```
deterministic:  1705ms  (budget: 5s)
candidates:     92 at R0 -> 40 returned
enrichment:     26/40 scored by Groq, streamed in behind the results
```

## Known gaps

- **Orizn free plan is capped at 5 requests until you confirm your email.**
  Clicking the confirmation link unlocks 100/month, free, no card. We spent the
  5 seeding 4 pairs (PAK→CHN/DEU/GBR/TUR). After confirming, re-run
  `python -m app.ingest.visa_sources` to seed more; `--repair-evidence`
  rebuilds the structured cache from the existing corpus at no quota cost.
  The free plan is also licensed for non-commercial evaluation only.
- **45 of 251 programmes have no inferred field of study**, so they are not
  field-filtered and appear for everyone. Untagged is deliberately safer than
  mis-tagged, but a real taxonomy would beat keyword matching.
- **DAAD publishes no fixed deadlines** ("updated annually in the second
  quarter"), so those rows carry a note instead of a date. Not a parser bug —
  the date genuinely is not on the page.
- `Base.metadata.create_all` on startup. Fine while the schema moves; switch to
  Alembic before the first migration under live rows.
- Vercel deploy is configured but not run — set `API_ORIGIN` to the deployed
  backend and `vercel deploy` (CLI not installed in this environment).
