# Presentation — corrected copy

Revisions to `Presentation 6`, checked slide by slide against the shipped code
on 13 Sep 2026. Slides not listed below are accurate and need no change.

Each correction says **what is on the slide now**, **what to put there**, and
**why it matters** — because two of these are claims a technical judge can
disprove in under a minute, and one of them is a privacy claim.

---

## Slide 3 — "Our Solution"

### Change one bullet

| Now | Replace with |
|---|---|
| **No Account Required**<br>0 accounts. Nothing retained. | **No Account Required**<br>No sign-up. Anonymous, and auto-deleted after 7 days. |

**Why.** "0 accounts" is true and worth saying. "Nothing retained" is not true.
For the session lifetime the database holds the OCR text of the uploaded
document (up to 20,000 characters), the profile, the match runs and the AI
explanations. The uploaded *file* is never written to disk — that part is real
and worth claiming — but the *text* is stored.

This is the kind of absolute a judge probes, and the accurate version is still a
strong claim: no account, nothing linked to a person, everything gone in 7 days,
and a delete button that erases immediately rather than queuing a job.

**If asked, the precise answer is:** "The file is processed in memory and never
written to disk or object storage. The extracted text lives on an anonymous
session row and is hard-deleted with it — there is no users table to link it to
anyone."

---

## Slide 9 — "Tech Stack"

Three factual errors. Everything else on this slide is correct and matches
`package.json` and `config.py` exactly.

| Block | Now | Correct |
|---|---|---|
| Deployment | Vercel · Docker / **SnapDeploy** | Vercel · Docker / **Render** |
| Database | PostgreSQL 17 · SQLAlchemy 2.0 · **Alembic** | **Neon** PostgreSQL 17 · SQLAlchemy 2.0 |
| Backend | **Python 3.12** · FastAPI + Uvicorn · Pydantic v2 | **Python 3.13** · FastAPI + Uvicorn · Pydantic v2 |

**Why each matters:**

- **Render, not SnapDeploy.** The API is on `scholarcompass.onrender.com`. The
  slide names a host that isn't serving.
- **Drop Alembic.** It's a dependency but there is no `alembic/` directory and
  no `alembic.ini`. The schema is created by `create_all` at startup. Our own
  README lists "no Alembic" as a known gap — a judge who greps finds the
  contradiction immediately. Say Neon instead; it's true and more interesting.
- **Python 3.13.** The API image is `python:3.13-slim`. Only the CI scraper runs
  3.12.

### Correct as-is — do not change

Frontend (Next.js 16.3.5 · React 19.2.8 · TypeScript 5 · Tailwind v4 ·
shadcn/ui · Lucide), AI/LLM (Groq · `gpt-oss-20b` match · `gpt-oss-120b` RAG),
OCR, Testing, and Retrieval ("PostgreSQL Full-Text Search · No Vector
Database"). All verified against source.

---

## Slide 12 — "Security, Trust & Privacy"

### Change one card

| Now | Replace with |
|---|---|
| **No Account Required**<br>• Nothing retained. | **No Account Required**<br>• Anonymous session, auto-deleted after 7 days.<br>• One click erases it immediately. |

Same reason as slide 3.

### The other three cards are exactly right — lean on them

All three are true and unusually defensible:

- **Nationality-Aware Filtering** — "Passport restrictions are respected at
  every eligibility level" is literally true. Nationality is never relaxed at
  any rung, including the loosest, and it's asserted in the test suite.
- **AI Score ≠ Eligibility Decision** — true. The model ranks only candidates
  that already passed the deterministic filters; it cannot add or remove one.
- **Passport-Gated Visa Panel** — true.

---

## Two slides worth adding

The deck currently omits the two strongest engineering stories in the project.
Both are differentiators, and one of them is the core of the product.

### New slide — "Never Show What You Can't Apply For"

> **H O W   W E   B R O A D E N   A   S E A R C H**
>
> When an exact search returns too little, we widen it **predictably** — and
> label every compromise.
>
> | | Relaxed | Labelled on the card |
> |---|---|---|
> | **R0** | nothing | Exact match |
> | **R1** | funding type | Partial funding |
> | **R2** | language minimum | Needs a test score |
> | **R3** | GPA by 0.3 | Slightly above your GPA |
> | **R4** | deadline, within 12 months | Closed — next cycle |
> | **R5** | field of study | Outside your field |
>
> **Never relaxed — at any level:** nationality restrictions, degree level, age caps.
>
> GPA relaxes *before* deadline on purpose: a near miss that is still open beats
> a perfect fit that closed last month.

**Why this slide.** It is the core of the product and the clearest answer to
"how is this different from a search box". It also demonstrates the judgement
behind the ordering, which is the part that reads as engineering rather than
plumbing.

### New slide — "Built for a 512MB Box"

> **E N G I N E E R I N G   C O N S T R A I N T S**
>
> The API runs in a hard 512MB container. Every dependency choice is a memory
> budget:
>
> - **No vector database** — Postgres full-text search. The visa corpus is full
>   of exact terms (`X1 visa`, `JW202`) where lexical retrieval beats embeddings.
> - **No browser at request time** — Playwright + Chromium (~400MB) runs weekly
>   in GitHub Actions and writes straight to Neon.
> - **No Redis** — the cache is a Postgres table, content-addressed by SHA-256
>   of the whole prompt.
>
> **Result — identical repeat search:**
>
> | | Cold | Warm |
> |---|---|---|
> | Deterministic results | 4.5 s | **21 ms** |
> | Groq calls | 40 | **9** |
>
> *Measured on the live deployment.*

**Why this slide.** "We made it fast" is a claim; a before/after with a
mechanism is evidence. It also explains *why* the architecture looks the way it
does, which pre-empts "why no vector DB?"

---

## Numbers you can defend if challenged

Every figure below was measured, not estimated. Quote the environment when you
quote the number — the local and production figures differ and conflating them
would be the easy thing to get caught on.

| Claim | Value | Where measured |
|---|---|---|
| Deterministic pass, warm cache | 21 ms | Production (Vercel → Render → Neon) |
| Deterministic pass, cold | 4.5 s | Production, first request |
| Scores replayed from cache | 31 of 40 | Production, second identical search |
| Full enrichment, cold → warm | 34.6 s → 15.9 s | Local Postgres, live Groq |
| Automated tests | 86 | Whole suite, none needs a database |
| Rate limit | 5/min match, 10/min visa | Verified: 6th request returns 429 |

**If asked "is the rate limit a security feature?"** — say no, and say why: the
API answers on its own public hostname, so a caller who skips the frontend can
spoof the forwarded-for header. It is a cost control against ordinary looping,
not a boundary against deliberate quota exhaustion. Closing it means making the
origin refuse unproxied traffic. Knowing the limit of your own control reads far
better than overclaiming it.

**If asked about the Match Score** — it is a 0–100 compatibility indicator from
the model, shown as "AI-assessed fit · not an eligibility decision". It is *not*
currently decomposed into weighted factors; PRD v1.2 §10 specifies that and it
is the top item on our roadmap. Saying so is stronger than being caught
implying otherwise.

---

## Before the demo

1. **Set `NEXT_PUBLIC_API_URL`** on Vercel and redeploy. The keep-alive
   currently pings the frontend's own 404 instead of the backend, so the
   container still cold-starts — the difference between a 21 ms first
   impression and a 4.5 s one.
2. **Hit the live site once** a few minutes before presenting, to warm both the
   Vercel function and the Render container.
3. **Run the same search twice** during the demo. The second one is instant and
   the `run` event reports what was reused — that is the caching slide proving
   itself live.
