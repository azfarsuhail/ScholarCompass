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
cd api && .venv/Scripts/python -m pytest        # 34 tests
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
to Neon — measured 250–271ms against a 5s budget. It is a pure function over
plain dicts, so it is tested without a database.

## Privacy

No accounts. A signed `HttpOnly` cookie carries an opaque session UUID and
nothing else. Uploads are OCR'd and discarded — only the extracted grade is
kept. A background sweeper hard-deletes expired sessions, and `DELETE
/v1/session` erases everything immediately.

Verified: forged cookies are rejected and re-issued, and after deletion the old
cookie resolves to a brand-new empty session.

## Known gaps

- **Orizn's free plan is licensed for evaluation / non-commercial use only**
  (it says so in the response body). A paid plan is required before launch.
- The visa RAG corpus (`visa_source_chunks`) has no crawler feeding it yet —
  the pipeline, retrieval and citation discipline are built and tested, but
  it returns `None` until official pages are ingested.
- `Base.metadata.create_all` on startup. Fine while the schema moves and there
  is no production data; switch to Alembic before the first migration under
  live rows.
- Vercel deploy is unconfigured (`API_ORIGIN` needs to point at the deployed
  backend). The CLI was not installed in this environment.
