# ScholarCompass — Product Requirements (as built)

**v2.0 · September 2026 · supersedes PRD v1.2 for the shipped system**

This document specifies ScholarCompass **as it exists**. Every requirement
below is implemented and verified unless it appears in §14 (Roadmap), which
lists what is deliberately not built and what is genuinely missing.

It is written this way on purpose. PRD v1.2 was an aspiration document, and
measuring the build against it produced a list of "gaps" that mixed three very
different things: work not yet done, work deliberately declined, and
requirements the build satisfies by a different mechanism than v1.2 imagined.
Section 13 separates those out. A reader holding v1.2 can map across by section
number, which is preserved where the subject matter is the same.

**Verification status** is marked on every requirement:

- ✅ implemented, covered by an automated test or a module self-check
- ☑️ implemented, verified manually against the live deployment
- ⚠️ implemented with a stated limitation
- ❌ not built — see §14

---

## 1. Product definition

ScholarCompass is a no-login web platform that helps a student discover
scholarships they are actually eligible for, understand why each one fits, and
see what the destination country's visa route requires — in one pass, without
creating an account.

**The product promise:** eligible opportunities, an explainable fit judgement,
and source-backed visa readiness.

### 1.1 The governing idea

> Eligibility is a database question with a right answer. Fit is a judgement
> call. Only the second one gets a model.

This is the single design constraint from which most of this document follows.
If a scholarship's published rules bar a student, no model output may put it on
their screen. Everything the LLM produces is **additive**: with no `GROQ_API_KEY`
configured the product still returns complete, ranked, explained results — it
simply loses the prose. ✅

---

## 2. Principles

| Principle | How it is enforced |
|---|---|
| **Hard constraints stay hard** | Nationality and degree level are rejected in SQL and again in the ladder, at every rung including the loosest. ✅ |
| **Evidence first** | A visa answer whose citations do not resolve to a supplied source is **discarded**, not flagged. ✅ |
| **Progressive value** | Deterministic results stream before any model call. Enrichment is a later event on the same stream. ✅ |
| **Freshness is measurable** | Every scholarship row carries `last_verified_at`; the UI renders it, including the unflattering states. ✅ |
| **Degrade, never fail** | Each external dependency has a defined degradation (§10.4), not an exception path. ✅ |
| **Say the uncomfortable thing** | "Not verified", "Closed — next cycle", "We could not verify this route" are first-class UI states. ✅ |
| **Privacy by omission** | The cheapest way not to leak a student's data is not to hold it. There is no users table. ✅ |

---

## 3. Users and primary flow

One user: a prospective international student, unauthenticated, on any device.

```
/          landing
/start     profile — CV/transcript upload or manual entry, always reviewable
/results   progressive matches → direct handoff to the official application page
```

3.1 No account is required, and none may be offered. ✅
3.2 The student may correct any extracted value before matching. A typed value
always outranks an OCR-derived one. ✅
3.3 Each result links **directly** to the programme's own application page, in a
new tab. No interstitial detail page, no affiliate hop. ✅
3.4 The shortlist is session-local to the browser (§8). ☑️

---

## 4. Profile and document processing

4.1 Accept CV/résumé and transcript as PDF, PNG, JPEG, WebP or TIFF. ✅
4.2 Reject anything else with a 415 naming the received type. A PDF arriving as
`application/octet-stream` — which is what mobile browsers send — is accepted
after `%PDF-` magic-byte sniffing. ✅
4.3 Extract education, grades, degree level, field, institution, dates, skills
and experience. Extraction failure is non-fatal: the form stays empty and the
student types. ✅
4.4 A CV extraction is presented **for review** and is not written to the session
until the student submits the form. A transcript's grade may prefill, but never
overwrite a value the student typed. ✅
4.5 Report extraction confidence, and distinguish a real PDF text layer from a
recognition guess. ✅
4.6 Never infer an eligibility fact that is not in the document. ✅

**Not built:** degree certificate and SOP as distinct document types; an
asynchronous extraction-status endpoint (extraction is synchronous). ❌ §14

### 4.7 Grade normalisation

4.7.1 Detect the grading scheme from country context rather than assuming a 4.0
GPA. ✅
4.7.2 Support percentage bands (per country), 4-point, 10-point CGPA, German
1.0–5.0, French /20, and UK honours classifications. ✅
4.7.3 Preserve the original value and scale alongside the normalised one, and
carry a confidence with every conversion. ✅
4.7.4 A low-confidence OCR GPA (< 0.7) receives ±0.3 tolerance at R0, so a scan
artefact cannot silently hide an eligible scholarship. The same number typed by
the student is taken at face value. ✅

> **Why this is not `percentage / 100 * 4`.** That formula is wrong in the
> direction that harms students: 62% is a First Division in Pakistan (~3.3) and
> a D in the US (~1.0). German grades run backwards, so a linear map inverts the
> ranking outright.

**Limitation:** OCR is English-only. Multilingual extraction is not built. ⚠️ §14

---

## 5. Data ingestion

5.1 Scholarship data is treated as a continuously changing external system.
Ingestion must survive JS-rendered pages, layout changes and stale listings. ✅
5.2 Attempt a plain HTTP fetch first; fall back to a headless browser only when
the page is a near-empty shell (< 600 visible characters plus SPA markers). ✅
5.3 Crawling runs **outside the API container** — GitHub Actions, weekly, Sunday
00:00 UTC, writing directly to Neon. Playwright plus Chromium is ~400MB and no
request path needs it. ✅ §9.1
5.4 Crawl strictly serially — one browser, one tab, one page at a time, with
images/fonts/media blocked at the network layer — so peak memory does not track
catalogue size and rate-limiting sites return pages rather than challenges. ✅
5.5 Each crawler step is independent: one source being down must not cost the
others. ✅
5.6 Record `last_verified_at`, `fetch_strategy` (`http` | `playwright`) and a
content hash on every row. ✅
5.7 Catalogue text must never enter the visa corpus. "What visa do I need?" must
not be able to retrieve a scholarship deadline. ✅

**Not built:** link-health checking, source trust tiers, source state machine,
canonical-key deduplication. Dedup is `slug` uniqueness only. ❌ §14

---

## 6. Deterministic eligibility — the R0–R5 ladder

The core of the product. **No model runs in this path.**

6.1 One coarse SQL query applies only the constraints that no rung relaxes;
the ladder then runs in memory over plain dicts. Six round-trips to a
network-attached database would spend the latency budget on their own. ✅

6.2 The ladder, ordered by how much the student would have to change:

| Rung | Relaxes | Shown to the student as |
|---|---|---|
| **R0** | nothing | Exact match |
| **R1** | funding type | Partial funding |
| **R2** | language minimum | Needs a test score |
| **R3** | GPA by 0.3; work-experience hours by 20% | Slightly above your GPA |
| **R4** | deadline, closed within 12 months | Closed — next cycle |
| **R5** | field of study | Outside your field |

✅ Covered by the matching suite and a database-free module self-check — the
ladder is a pure function over plain dicts precisely so the logic most likely to
be quietly wrong can be tested without a database.

6.3 **Never relaxed at any rung, including R5:**
- nationality exclusions and whitelists (an empty whitelist means *open to all*,
  not *nobody*)
- degree level
- a stated age cap

✅ Each asserted individually.

6.4 A passed deadline may appear **only** at R4 and is always labelled closed. A
call more than 12 months dead never appears. ✅

6.5 GPA relaxes *before* deadline, deliberately: a 2.9-against-3.0 near miss that
is still open beats a perfect fit that closed last month. ✅

6.6 A candidate is tagged with the **first** rung that admitted it and appears
exactly once. An exact match is never relabelled a stretch because a later rung
also ran. ✅

6.7 An unstated requirement is not a barrier — a scholarship that does not
publish a GPA minimum does not filter on one. ⚠️ It is also not currently
surfaced as "Verify eligibility" (§14).

6.8 Stop descending once 12 results are held (configurable). The reported
relaxation level is the deepest rung that actually **contributed** a candidate,
not the last rung executed — otherwise a small corpus would report a widened
search when every result was exact. ✅

6.9 Disclose in the UI whenever the search was widened. ✅

---

## 7. Semantic fit and the Match Score

7.1 The model ranks and explains **among candidates already proven eligible**.
It cannot add a scholarship, cannot remove one, and its score never gates
visibility — a candidate whose LLM call failed still renders, without prose. ✅

7.2 Return a 0–100 fit score, a rationale addressed to the student, matched
criteria, and gaps. The deterministic gaps are authoritative; the model may only
add to them. ✅

7.3 The score is a compatibility indicator and **must never** be presented as a
probability of acceptance. The card reads "AI-assessed fit: N/100 · not an
eligibility decision". ☑️

7.4 Bound the work: 12-second timeout per candidate, at most 5 concurrent calls,
results yielded in completion order so the UI animates each card as it lands
rather than stalling on the slowest. ✅

7.5 Cancel in-flight model calls when the client disconnects. ✅

> **Divergence from v1.2 §10.** That document specifies a weighted, decomposable
> score (Academic 25 / Field 20 / Eligibility 15 / Funding 15 / Destination 10 /
> Experience 10 / Deadline 5) with a reproducible `score_version`. **This is not
> built.** What ships is a single opaque model judgement. See §14 — it is the
> largest outstanding gap and the one a reader of v1.2 will look for first.

---

## 8. Compare and shortlist

8.1 A student may save up to 8 scholarships and view them side by side in a
comparison table. ☑️
8.2 The shortlist lives in `localStorage` and **is never sent to the server**. ☑️
8.3 A saved entry stores a snapshot, not an id, so the panel survives a reload
or a fresh search. ☑️
8.4 Storage is unavailable or throws (private mode, blocked site data) → the
feature degrades to session-lifetime, never a broken render. ☑️

> **Divergence from v1.2 §15.** `POST /v1/matches/compare` is specified and was
> deliberately not built. Comparing is a private act of deliberation; a
> shortlist on the server would be a new durable statement of intent attached to
> a session id, in exchange for a feature that works perfectly without one.

---

## 9. Visa readiness

9.1 Structured verdict and narrative are **unequal by design**. The structured
requirement from the upstream provider is the answer; the RAG narrative is
commentary. If they disagree, the structured value wins. ✅

9.2 A pair we cannot verify returns an honest "Unknown" with advice to check
with the embassy. A fabricated visa verdict is the most expensive possible error
for a student. ✅

9.3 Categories surfaced: required documents, financial / proof-of-funds, the
application process, passport validity, insurance where applicable. ✅

9.4 Retrieval is Postgres full-text search over stored chunks, ranked so that a
page written for the student's nationality outranks a general one, and a page
written for a *different* nationality is never returned. ✅

9.5 **Every material claim carries a citation that resolves to a supplied
source.** An answer with no resolvable citation is discarded. ✅

9.6 Report two distinct dates and never conflate them: the publisher's own
verification date, and when we fetched it. ✅

9.7 The visa panel requires a passport and prompts for one rather than spending
a round-trip to earn a 400. ☑️

9.8 Proof-of-funds items are a derived *view* of the document list, not a
separate claim. Insurance and fees are excluded — they are costs to meet, not
evidence of means. ✅

> **Why lexical retrieval, not vectors.** The corpus is small, highly
> structured, and full of exact terms a student's question repeats verbatim
> (`X1 visa`, `JW202`, `residence permit`). The inference provider has no
> embeddings endpoint and a local embedding model would not fit the container.
> Vectors would be added weight for worse exact-term recall.

---

## 10. Non-functional requirements

### 10.1 Deployment and resource budget

| Component | Host |
|---|---|
| Web (Next.js 16, React 19, Tailwind v4) | Vercel, `fra1` |
| API (FastAPI, Python 3.13, one uvicorn worker) | Render, 512MB container |
| Database | Neon PostgreSQL |
| Crawlers (Playwright + Chromium) | GitHub Actions, weekly |
| Inference | Groq — `gpt-oss-20b` (match), `gpt-oss-120b` (RAG) |

10.1.1 The API container must stay within 512MB. This is a **design input**, not
an aspiration: no torch, no embeddings, no Redis, no second worker. OCR is the
Tesseract binary. ✅
10.1.2 The API image must never import Playwright. ✅
10.1.3 The API is proxied same-origin: the web app rewrites `/api/*` to the
backend. This is load-bearing, not tidiness — the session cookie is
`HttpOnly; SameSite=Lax`, and browsers do not send Lax cookies cross-site.
Pointing the browser at another domain would mint a fresh empty session on every
request. ☑️
10.1.4 The rewrite target must tolerate a trailing slash. ✅

### 10.2 Latency

| Stage | Target | Measured |
|---|---|---|
| Deterministic results | p95 ≤ 5s | 4.5s cold, **21ms** warm (production) ☑️ |
| AI enrichment | p95 ≤ 30s | 34.6s → **15.9s** warm (local, live Groq) ☑️ |
| Visa panel | asynchronous | ☑️ |

10.2.1 Exceeding the deterministic budget must log a warning with the candidate
count. ✅
10.2.2 Every run records its own deterministic and enrichment timings, so the
contract is provable in production and not only in tests. ✅

⚠️ The cold deterministic path has almost no headroom against the 5s target.
Neon round-trip plus function cold start dominates; the cache is what makes the
warm path fast.

### 10.3 Cost control and caching

10.3.1 Cache expensive deterministic artifacts in Postgres, **content-addressed
by SHA-256 of the inputs**. A stale read must be impossible by construction:
change any input and you address a different row. ✅

| Artifact | Key | TTL |
|---|---|---|
| `match_score` | SHA-256 of the entire prompt — system text, model name and rendered user message | 7 days |
| `deterministic` | SHA-256 of the profile + result-count setting | 15 minutes |
| Visa verdict | passport + destination | 24 hours |
| Visa narrative | passport + destination | 7 days |

10.3.2 Editing the scoring prompt must invalidate every stored score with no
version constant to remember. (It is inside the hash.) ✅
10.3.3 Score lookups are **one** batched query, never one per candidate. ✅
10.3.4 A cache write must cost no extra round-trip — it rides inside the
transaction that persists the explanation. ✅
10.3.5 The deterministic entry is written **after** first paint, so a cache miss
pays nothing on the path the cache exists to protect. ✅
10.3.6 A cache failure is logged and swallowed. The cache is never load-bearing. ✅
10.3.7 Expired cache rows are swept alongside expired sessions. ✅

### 10.4 Fault tolerance

| Failure | Required behaviour |
|---|---|
| No API key configured | Full ranked deterministic results, no prose ✅ |
| Model slow | Per-candidate timeout; that card renders unenriched ✅ |
| Model down | Enrichment events stop; delivered matches stay ✅ |
| Cache read/write fails | Logged, treated as a miss ✅ |
| Visa provider unreachable | Honest "Unknown", never a guess ✅ |
| RAG answer uncited | Discarded ✅ |
| Client disconnects | In-flight model calls cancelled ✅ |

### 10.5 Abuse control

10.5.1 Rate-limit the expensive routes per caller: 5/min on the match stream
(which fans out to as many as 40 model calls), 10/min on the visa check (whose
`explain=true` path runs the larger model). ✅
10.5.2 Refusals must carry `Retry-After`. ☑️
10.5.3 The bucket must key on the **originating browser**, not the proxy.
Keying on the socket address would place every user in one shared bucket. ✅

> ⚠️ **Stated limitation.** The API answers on its own public hostname, not only
> through the proxy — bot traffic in the origin logs confirms it. A caller who
> skips the frontend can therefore spoof the forwarded-for header and mint a
> fresh bucket per request. **This limit is a cost control against ordinary
> looping, not a security boundary against deliberate quota exhaustion.**
> Closing it requires the origin to refuse unproxied traffic.

10.5.4 Uploads are capped at 10MB per file, rejected **before** the body is
parsed or spooled to disk. ✅
❌ Per-session document-count and total-byte caps are not built. §14

---

## 11. Security and privacy

11.1 There is no users table. Identity is an opaque, expiring session row. ✅
11.2 The cookie carries a signed session UUID and nothing else. A forged cookie
is rejected and re-issued; after deletion the old cookie resolves to a brand-new
empty session. ✅
11.3 `DELETE /v1/session` erases everything immediately — not a soft delete, not
a queued job. ✅
11.4 A sweeper hard-deletes expired sessions every 15 minutes; cascades take
documents, runs and explanations. ✅

11.5 **What is actually retained**, stated precisely because the easier sentence
would be false:

| Kept for the session lifetime | Never stored |
|---|---|
| OCR **text** (≤ 20,000 chars) | The uploaded **file** — processed in memory, never written to disk or object storage |
| Normalised grade + confidence | Any name, email or contact detail — the profile allow-list accepts none |
| Profile, match runs, explanations | Any link between a session and a person |

☑️ "No accounts" is true. "Nothing retained" is **not** true and must not be
claimed in any user-facing copy or presentation.

11.6 Visa evidence is deliberately **not** session-scoped. A passport +
destination pair attached to a session id is a travel-intent record about a
person; the same pair standing alone is public reference data. Keeping it global
caches better *and* deletes the only row that could profile a student. ✅

11.7 The score cache is likewise global. A hit requires a byte-identical prompt,
and prompts are built only from profile fields, so the only caller who can read
an entry already holds everything it was derived from. ✅

11.8 Treat uploaded and retrieved content as untrusted input. ✅
11.9 Decompression-bomb protection: images are downsampled before OCR. ✅
11.10 No provider secrets reach the frontend. ✅
❌ Malware scanning is not built. §14

---

## 12. Interfaces

### 12.1 API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + database check ☑️ |
| `GET /v1/session` | Read own session; mints transparently ☑️ |
| `DELETE /v1/session` | Erase everything now ✅ |
| `POST /v1/documents` | Upload + OCR + extract ✅ |
| `PUT /v1/profile` | Merge allow-listed profile fields ✅ |
| `GET /v1/match/stream` | Progressive SSE results ☑️ |
| `GET /v1/visa/check` | Verdict + readiness + optional RAG narrative ☑️ |
| `GET /v1/visa/requirements` | The requirement enum the UI renders ☑️ |

### 12.2 The match stream

```
event: run         run opened — relaxation level, per-rung counts, cache stats
event: match       one eligible scholarship (deterministic, no model)
event: enrichment  one model score, keyed back to a match
event: done        finished — enriched count, cache hits
```

12.2.1 Every event after `match` is additive. ✅
12.2.2 The `run` event discloses what was reused from cache, so an instant
second search is explainable rather than suspicious. ☑️
12.2.3 Proxy buffering must be disabled, or the progressive stream degrades into
one slow blob. ✅

### 12.3 UI requirements

12.3.1 Each card shows the eligibility label, provider, country, deadline, gaps,
binding obligations, and a freshness badge. ☑️
12.3.2 Freshness has three honest states: verified within 48h, verified longer
ago, and **never verified**. ☑️
12.3.3 A deadline the publisher announces annually must read differently from
one we failed to find. ✅
12.3.4 Obligations that do not affect eligibility but bind a student for years —
a two-year return rule, a home-residency requirement — are **always shown, never
filtered on**. ✅
12.3.5 Colour may never be the sole carrier of meaning. ☑️
12.3.6 Respect `prefers-reduced-motion`. ☑️

---

## 13. Deliberate divergences from PRD v1.2

These are decisions, not omissions. Each is a case where v1.2's mechanism was
rejected in favour of a different one.

| v1.2 | Built instead | Why |
|---|---|---|
| §6.2 ladder relaxes destination → subject → institution → funding → deadline | funding → language → GPA/work-hours → deadline → field | v1.2's ladder relaxes preferences the product does not collect (institution) or filter on (destination). The built ladder relaxes what the corpus actually encodes. **Note this puts minimum GPA and a valid deadline — both listed as *hard* constraints in v1.2 §6.1 — inside the ladder.** Both are labelled at every rung; nothing is silently relaxed. |
| §15 `POST /v1/matches/compare` | `localStorage` shortlist | §8 |
| §15 `GET /v1/scholarships/{id}` | Direct handoff to the provider | An intermediate detail page adds a hop between a student and the real application form |
| §8 embeddings cache | Postgres full-text search | §9 |
| §14 `GradingNormalization` entity | JSONB on the document row | The shape genuinely varies by country; normalising it into columns would force invented values |
| §14 `VisaEvidence` session-scoped | Global | §11.6 — global is the *more* private choice |

---

## 14. Roadmap — what is genuinely missing

Ordered by what a reader of v1.2 will notice first.

1. **Decomposable Match Score.** v1.2 §10, §10.1, §18 and §19 all require a
   weighted score with a visible factor breakdown and a reproducible
   `score_version`. `MatchRun` has no `score_version` or `constraints_applied`;
   `MatchExplanation` has no `factor_scores` or `unknown_requirements`. This is
   the single largest gap.
2. **"Verify eligibility" for unknowns.** v1.2 §6.2 requires unknown
   requirements to surface as *verify*, not *pass*. Today they pass silently
   (§6.7). The string does not exist in the codebase.
3. **Link health.** No URL checking, no `LinkCheck`, no `SourceHealth`, no
   redirect classification. v1.2 §19's "a 404 is not labelled closed" passes
   only vacuously — nothing checks.
4. **Canonicalisation and deduplication.** Dedup is `slug` uniqueness. No
   canonical key, no URL normalisation, no conflicting-evidence retention.
5. **Upload quotas.** Per-file size is capped; per-session document count and
   total bytes are not.
6. **Alembic.** `create_all` runs at startup, which creates missing *tables* but
   never missing *columns*. Schema changes need hand-written DDL. This is the
   first thing to fix before the schema moves under live rows.
7. **Field-of-study taxonomy.** Inference is keyword matching; untagged
   programmes are not field-filtered and appear for everyone. Untagged is
   deliberately safer than mis-tagged, but a real taxonomy would beat it.
8. **Multilingual OCR**, malware scanning, a document-status endpoint, and a
   `POST /v1/visa/refresh` route (refresh is a CLI worker today).

---

## 15. Acceptance criteria

Each is automated or was verified against the live deployment.

1. A student barred by nationality never sees that scholarship at any rung,
   including the loosest. ✅
2. An empty nationality whitelist means open to all, not open to nobody. ✅
3. Degree level is never relaxed. ✅
4. A closed deadline never appears before R4, and is always labelled closed. ✅
5. A call more than 12 months dead never appears. ✅
6. An unstated requirement never acts as a barrier. ✅
7. A low-confidence OCR GPA receives tolerance; the same figure typed does not. ✅
8. A candidate is tagged by the first rung that admitted it and appears once. ✅
9. With enough exact matches, the ladder never descends. ✅
10. Deterministic results reach the client before any model output. ☑️
11. With no API key, results are still complete, ranked and explained. ✅
12. The Match Score is never presented as an acceptance probability. ☑️
13. A visa answer with no resolvable citation is discarded, not shown. ✅
14. A visa route we cannot verify returns "Unknown", never a guess. ✅
15. An identical repeat search spends zero model calls. ☑️
16. Cached and freshly generated scores are indistinguishable in content and
    both persist as explanations. ✅
17. A rate-limited caller receives 429 with `Retry-After`; a different caller is
    unaffected. ✅
18. Every profile field the matcher reads survives the profile write. ✅
19. A forged cookie is rejected and re-issued; after deletion the old cookie
    resolves to a new empty session. ✅
20. An oversized upload is rejected before the body is parsed or spooled. ✅

**Current status: 86 automated tests, four module self-checks, zero requiring a
database.**

---

## 16. Outcome

ScholarCompass treats scholarship discovery as a continuously verified data
product rather than a one-time search. It gives fast deterministic value,
manages uncertainty explicitly, handles international academic records without
inventing equivalences, broadens searches predictably and visibly, explains why
an opportunity fits without ever letting that explanation decide eligibility,
connects a recommendation to its visa route with citations, and keeps anonymous
AI usage economically sustainable inside a 512MB container.

Where it falls short of PRD v1.2, §13 says which shortfalls were chosen and §14
says which were not.
