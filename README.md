# ScholarCompass

Anonymous scholarship discovery and visa readiness. Hard deterministic
eligibility filtering first, an LLM for semantic fit second, and a separate
citation-bound RAG pipeline for visa requirements.

```
web/   Next.js 16 · Tailwind v4 · Motion          → Vercel (fra1)
api/   FastAPI · SQLAlchemy 2.0 · asyncpg         → Render (512MB hard cap)
db     Neon PostgreSQL (serverless, pooled)
jobs   Playwright crawlers                        → GitHub Actions (weekly)
llm    Groq LPU inference                         → gpt-oss-20b / gpt-oss-120b
```

---

## 1. Project overview & current specs

**The one idea.** Eligibility is a database question with a right answer. Fit is
a judgement call. Only the second one gets a model.

If a scholarship's rules bar you, no amount of AI enthusiasm puts it on your
screen. Everything the LLM produces is *additive*: with no `GROQ_API_KEY` set
you still get complete, ranked, explained results — just without the prose.

### The four constraints we engineered against

#### 512MB container isolation

The API image is Tesseract + FastAPI + asyncpg and nothing else. The
dependency list is a memory budget, not a convenience:

- **No torch.** OCR is the Tesseract binary (~45MB with the English pack).
- **No embeddings.** RAG retrieval is Postgres full-text search. Groq has no
  embeddings endpoint, and a local embedder would blow the container on its
  own. The visa corpus is small and full of exact terms a student repeats
  verbatim — `X1 visa`, `JW202`, `residence permit` — where lexical retrieval
  is genuinely strong.
- **No Redis.** Rate-limit counters are an in-process dict; the cache is a
  Postgres table. A second datastore buys cross-container accuracy we have no
  second container to need.
- **One uvicorn worker.** Each worker is a full Python process (~90MB RSS);
  two of them plus a Tesseract subprocess (~60MB peak/page) OOMs in 512MB. We
  scale with containers, not workers. The workload is IO-bound anyway.

`docker-compose.yml` sets `mem_limit: 512m` locally, so an OOM surfaces on a
laptop rather than in production.

#### Offline asynchronous scraping

Playwright plus Chromium is ~400MB installed — it cannot coexist with the API
in 512MB, and no request path needs it. The crawlers therefore live in
`.github/workflows/weekly-scraper.yml` and write **straight to Neon**. The API
container never imports Playwright; `app/ingest/crawler.py` imports it lazily
so that stays true.

The crawl is strictly serial — one browser, one tab, one page at a time, with
images/fonts/media blocked at the network layer — so peak memory does not track
catalogue size, and EU/government sites that block parallel scraping return
pages instead of 429s. Flagship crawls run under `if: ${{ !cancelled() }}`, so
one site being down does not cost us the other six.

#### SHA-256 prompt caching in Postgres

A match run fans out to as many as 40 Groq completions. Repeat runs — a judge
refreshing, a student tweaking one field — used to pay that in full.

`retrieval_cache` is **content-addressed**: the key is a SHA-256 of the *entire
prompt*, system text and model name included. Consequences that fall out of
that design rather than out of discipline:

- A stale read is impossible by construction. Change the profile, the
  scholarship, the prompt or the model and you address a *different row*.
- Editing the `SYSTEM` prompt invalidates every stored score. There is no
  version constant to remember to bump.
- Cache reads are **one** `IN (...)` query for all 40 keys. Forty round-trips
  to a network-attached database would cost more than the Groq calls they save.
- The write rides inside the `MatchExplanation` transaction that was happening
  anyway, so remembering an answer costs **zero** extra round-trips.
- The deterministic entry is written *after* first paint, so a cache miss pays
  nothing on the latency path the cache exists to protect.

| Artifact | TTL | What it saves |
|---|---|---|
| `match_score` | 7 days | One Groq completion |
| `deterministic` | 15 min | The Neon round-trip + the R0–R5 ladder |

**Privacy.** Rows are not session-scoped. A hit requires a byte-identical
prompt, and prompts are built only from profile fields — `PROFILE_FIELDS`
accepts no name or contact detail. The only caller who can read an entry
already holds everything it was derived from.

#### Proxy-aware rate limiting

`slowapi`, ~800KB, pure Python, in-process storage.

| Route | Limit | Why |
|---|---|---|
| `/v1/match/stream` | 5/min/IP | Up to 40 Groq completions per call |
| `/v1/visa/check` | 10/min/IP | `explain=true` runs RAG on the *larger* model |

The subtle part: `next.config.ts` rewrites `/api/*` through the Next server, so
`request.client.host` is **always the proxy**. Keying on it would have put every
student on earth into one shared 5-per-minute bucket — the second visitor of any
minute throttled because of the first. `client_key()` keys on the first
`X-Forwarded-For` hop instead. Refusals carry `Retry-After`, per PRD §8.1.

**Stated limitation:** the API is reachable on its own public hostname, not
only through the proxy, so a caller who skips the frontend can spoof that
header and mint a fresh bucket per request. This limit is therefore a cost
control against ordinary looping, not a security boundary against someone
deliberately burning the Groq quota. Closing it means making the origin refuse
unproxied traffic — a shared secret injected by the rewrite, or network rules.

### Measured

Local Postgres, 251-row corpus, live Groq, single container:

| | Cold | Warm | Δ |
|---|---|---|---|
| Deterministic pass | 304 ms | **89 ms** | 3.4× |
| Scores served from cache | 0 / 40 | **27 / 40** | — |
| Wall clock to full enrichment | 34.6 s | **15.9 s** | 2.2× |

Rate limiter, fresh IP: requests 1–5 → `200`, 6–7 → `429` + `Retry-After: 60`.

Against the deployed stack (Vercel → Render → Neon) the same second search
returns its deterministic half in **21 ms** with 31 of 40 scores replayed from
cache. The first search after an idle period takes **4.5 s**.

> Two caveats, because these numbers are only useful with their conditions
> attached. The 304/89 ms figures above are **local Postgres**; against Neon the
> network dominates and a cold deterministic pass measures ~1.7 s. And the 4.5 s
> production cold figure is mostly not application work — Render's free tier
> spins the container down when idle, so the first request pays a container
> start too. That is what `web/components/KeepAlive.tsx` exists to prevent.

82 tests, no database required for any of them.

### Fault tolerance

Every external dependency has a defined degradation, not an exception path:

| Failure | Behaviour |
|---|---|
| No `GROQ_API_KEY` | Full ranked deterministic results, no prose |
| Groq slow | 12 s/candidate timeout; that card renders unenriched |
| Groq down | `enrichment` events stop; `match` events already delivered |
| Cache read fails | Logged, treated as a miss |
| Cache write fails | Logged and swallowed — never load-bearing |
| Orizn unreachable | Honest `"Unknown"`, never a guessed visa verdict |
| RAG answer uncited | **Discarded**, not flagged |
| Client disconnects | In-flight Groq tasks cancelled |

---

## 2. System architecture

```mermaid
graph TD
    subgraph client["Browser"]
        U["Student · no account"]
        LS["localStorage<br/>favorites + compare"]
    end

    subgraph vercel["Vercel · fra1"]
        NX["Next.js 16 App Router<br/>RSC · Tailwind v4 · Motion"]
        RW["Rewrite /api/* → backend<br/>keeps session cookie first-party"]
    end

    subgraph snap["Render · 512MB hard cap"]
        API["FastAPI · 1 uvicorn worker"]
        RL["slowapi<br/>in-process counters"]
        OCR["Tesseract OCR<br/>threadpool, in-memory"]
        LAD["R0–R5 ladder<br/>pure function"]
    end

    subgraph gha["GitHub Actions · weekly cron"]
        PW["Playwright + Chromium<br/>~400MB, serial crawl"]
    end

    subgraph neon["Neon PostgreSQL"]
        SCH[("scholarships")]
        SESS[("anon_sessions")]
        CACHE[("retrieval_cache")]
        VISA[("visa_source_chunks<br/>GIN full-text index")]
    end

    subgraph ext["External APIs"]
        GROQ["Groq LPU<br/>gpt-oss-20b / 120b"]
        ORIZN["Orizn<br/>visa requirement"]
    end

    U --> NX
    U <--> LS
    NX --> RW
    RW -->|"HttpOnly SameSite=Lax"| RL
    RL --> API
    API --> OCR
    API --> LAD

    API -->|"asyncpg · pooled"| SESS
    LAD -->|"1 coarse query"| SCH
    API -->|"batched IN(...)"| CACHE
    API -->|"ts_rank FTS"| VISA

    API -.->|"cache miss only"| GROQ
    API -.->|"24h TTL"| ORIZN

    PW ==>|"writes rows directly<br/>never through the API"| SCH

    classDef ceiling stroke-dasharray: 5 5
    class snap,gha ceiling
```

The Playwright path is a **write-only side channel**. It shares the repo and
the models but never the container, which is what keeps the API image inside
its ceiling while the corpus stays fresh.

---

## 3. User flow

```mermaid
flowchart TD
    START(["Landing /"]) --> ONB["Anonymous onboarding /start"]

    ONB --> CHOICE{"How to build<br/>the profile?"}
    CHOICE -->|Upload| UP["PDF / image → Tesseract<br/>file discarded after OCR"]
    CHOICE -->|Manual| FORM["Typed profile"]

    UP --> GRADE["Grade normalisation<br/>per-country, piecewise<br/>carries a confidence"]
    GRADE --> REVIEW["Student reviews + corrects<br/>typed value outranks OCR"]
    FORM --> REVIEW

    REVIEW --> PROF[/"PUT /v1/profile<br/>degree · fields · GPA · passport<br/>skills · experience · work hours"/]

    PROF --> DET["Deterministic filtering<br/>R0–R5 ladder, no LLM"]

    DET --> GATE{"Hard gates"}
    GATE -->|"nationality barred<br/>or wrong degree level"| DROP["Never shown<br/>at any rung"]
    GATE -->|passes| RUNG["Tag by first admitting rung"]

    RUNG --> STREAM["GET /v1/match/stream · SSE"]
    STREAM --> PAINT["Deterministic cards paint<br/>ranked + explained"]
    PAINT --> ENRICH["AI fit scores stream in behind<br/>list re-ranks live"]

    ENRICH --> UI{"Student acts"}
    UI -->|Save| FAV["localStorage shortlist<br/>max 8, never sent to server"]
    FAV --> CMP["Compare panel<br/>side-by-side table"]
    UI -->|"Expand card"| VISA["GET /v1/visa/check<br/>documents · funds · process"]
    VISA --> CITE["Every material claim cited<br/>uncited answers discarded"]
    UI -->|Apply| OUT(["Official application page<br/>new tab, no interstitial"])

    CMP --> OUT
    CITE --> OUT

    style DROP stroke-dasharray: 4 4
    style OUT stroke-width:3px
```

**The R0–R5 ladder**, ordered by how much the student would have to change:

| Rung | Relaxes | Shown as |
|---|---|---|
| R0 | nothing | Exact match |
| R1 | funding type | Partial funding |
| R2 | language minimum | Needs a test score |
| R3 | GPA by 0.3; work hours by 20% | Slightly above your GPA |
| R4 | deadline, within 12 months | Closed — next cycle |
| R5 | field of study | Outside your field |

GPA relaxes before deadline on purpose: a near miss that is still open beats a
perfect fit that closed last month.

**Never relaxed at any rung, including R5:** nationality exclusions and
whitelists, and degree level. Closed deadlines appear only at R4 and are always
labelled closed.

The ladder runs in memory over one coarse SQL query rather than six round-trips
to Neon. It is a pure function over plain dicts, so it is tested without a
database — it is the logic most likely to be quietly wrong.

---

## 4. Sequence: `GET /v1/match/stream`

```mermaid
sequenceDiagram
    autonumber
    participant C as Next.js Client<br/>EventSource
    participant R as slowapi
    participant A as FastAPI
    participant P as Neon PostgreSQL
    participant G as Groq

    C->>R: GET /v1/match/stream
    R->>R: bucket = X-Forwarded-For[0]

    alt over 5/min
        R--xC: 429 + Retry-After: 60
    else within budget
        R->>A: dispatch

        Note over A,P: Deterministic half — the latency promise
        A->>A: det_key = sha256(profile ‖ min_results)
        A->>P: SELECT payload WHERE cache_key = det_key

        alt cache HIT
            P-->>A: 40 candidates · 89 ms
        else cache MISS
            P-->>A: no row
            A->>P: one coarse query<br/>hard gates only
            P-->>A: candidate rows
            A->>A: R0–R5 ladder in memory
        end

        Note over A,P: Score lookup — ONE query, not 40
        A->>P: SELECT WHERE cache_key IN (40 prompt hashes)
        P-->>A: 27 hits / 13 misses
        A->>P: INSERT match_runs
        P-->>A: run_id

        A-->>C: event: run<br/>{relaxation_level, cache:{...}}
        loop each candidate
            A-->>C: event: match (deterministic)
        end
        Note over C: First paint complete.<br/>Everything below is additive.

        A->>P: INSERT deterministic cache entry
        loop each cached score
            A-->>C: event: enrichment {cached: true}
        end

        par 13 cache misses · max 5 concurrent
            A->>G: score_one · 12s timeout
            G-->>A: {score, rationale, gaps}
        and meanwhile
            Note over C: Painted cards stay interactive
        end

        loop as each completes
            A-->>C: event: enrichment {cached: false}
            A->>P: INSERT explanation + cache entry<br/>ONE transaction
        end

        alt Groq unavailable or timed out
            A->>A: log, continue
            Note over C: Cards stay, unenriched
        end

        A->>P: UPDATE match_runs SET status='complete'
        A-->>C: event: done {enriched, from_cache}
    end
```

Enrichments are yielded in **completion order**, not input order, so the UI
animates each card as it lands instead of stalling on the slowest. A client
disconnect cancels in-flight Groq tasks.

---

## 5. Data model

```mermaid
erDiagram
    anon_sessions ||--o{ documents : "ON DELETE CASCADE"
    anon_sessions ||--o{ match_runs : "ON DELETE CASCADE"
    match_runs ||--o{ match_explanations : "ON DELETE CASCADE"
    scholarships ||--o{ match_explanations : "scored in"

    anon_sessions {
        uuid id PK "opaque, signed into an HttpOnly cookie"
        jsonb profile "degree_level, fields_of_study, gpa_4, gpa_source, gpa_confidence, age, funding_preference, language_scores, target_countries, institution, skills, experience, work_experience_hours"
        varchar3 passport_iso3 "denormalised out of profile for visa lookups"
        timestamptz expires_at "hard TTL, 72h · swept every 15 min"
    }

    documents {
        uuid id PK
        uuid session_id FK
        text ocr_text "extraction only — the upload is never written to disk"
        jsonb normalized "scheme, raw, gpa_4, percentage, confidence"
    }

    scholarships {
        uuid id PK
        varchar200 slug UK
        varchar3 host_country_iso3 "indexed"
        array degree_levels "NEVER relaxed"
        array eligible_nationalities "empty = open to all · NEVER relaxed"
        array excluded_nationalities "NEVER relaxed"
        array fields_of_study "relaxed at R5"
        numeric min_gpa_4 "relaxed 0.3 at R3 · CHECK 0..4"
        jsonb min_language_score "waived at R2"
        integer min_work_experience_hours "Chevening 2800h · relaxed 20% at R3"
        text return_obligation "shown, never filtered"
        text entry_requirement "shown, never parsed"
        varchar16 funding_type "relaxed at R1"
        date deadline "indexed · closed calls only at R4"
        timestamptz last_verified_at "drives the freshness badge"
        varchar16 fetch_strategy "http | playwright"
    }

    match_runs {
        uuid id PK
        uuid session_id FK
        varchar2 relaxation_level "deepest rung that CONTRIBUTED"
        jsonb level_counts "per-rung candidate counts"
        integer deterministic_ms "proves the budget in prod, not just in tests"
        jsonb profile_snapshot "run stays explainable after an edit"
    }

    match_explanations {
        uuid id PK
        uuid run_id FK
        uuid scholarship_id FK
        varchar2 entered_at_level "R0 renders 'exact', R3+ 'a stretch'"
        numeric semantic_score "0-100 · CHECK · never gates visibility"
        text rationale
        varchar64 model "groq | groq (cached)"
    }

    retrieval_cache {
        varchar64 cache_key PK "SHA-256 of the inputs — the key IS the identity"
        varchar24 artifact_type "match_score | deterministic"
        jsonb payload
        varchar80 version "model + prompt, readable so bad rows can be purged"
        timestamptz expires_at "indexed · 7d scores, 15min deterministic"
    }

    visa_evidence {
        uuid id PK
        varchar3 passport_iso3 UK "NOT session-scoped — see note"
        varchar3 destination_iso3 UK
        varchar24 requirement "visa_required | visa_free | e_visa | eta | ..."
        jsonb citations "never render summary without these"
        date source_last_verified "the publisher's date, not our fetch time"
    }

    visa_source_chunks {
        uuid id PK
        varchar3 destination_iso3 "indexed"
        varchar3 passport_iso3 "NULL = applies to all nationalities"
        tsvector search_vector "GENERATED in Postgres · GIN index"
        text content
    }
```

Three schema decisions worth the judges' time:

**`anon_sessions.profile` is JSONB, deliberately.** The shape genuinely varies
by country and degree, and we refuse to normalise PII into queryable columns.
`target_countries`, `skills`, `experience`, `institution` and
`work_experience_hours` are **keys inside this column**, not columns of their
own — the server-side allow-list in `merge_profile()` is what decides which of
them may be written at all, and it accepts no name or contact detail.

**`visa_evidence` is not session-scoped.** A passport+destination pair attached
to a session id is a travel-intent record about a person. The same pair standing
alone is public reference data. Keeping it global caches better *and* deletes
the only row that could profile a student.

**`retrieval_cache.cache_key` is the primary key, not a surrogate id.** That is
the whole mechanism: identity *is* the content hash, so an out-of-date read
cannot be expressed.

---

## Privacy

No accounts. A signed `HttpOnly` cookie carries an opaque session UUID and
nothing else.

Stated precisely, because "nothing is kept" would be easier to say and would
be false: the uploaded **file** is processed in memory and never written to
disk or object storage, but the **text** Tesseract read out of it is stored on
the session row (`documents.ocr_text`, capped at 20,000 characters) along with
the normalised grade, the profile, and the match runs. All of it is anonymous,
none of it is linked to a person, and all of it dies with the session — a
background sweeper hard-deletes expired sessions and expired cache rows every
15 minutes, and `DELETE /v1/session` erases everything immediately.

The shortlist never leaves the browser. `POST /v1/matches/compare` is in the
PRD; we deliberately did not build it. Comparing is a private act of
deliberation, and a shortlist on the server would be a new durable statement of
intent attached to a session id — in exchange for a feature that works
perfectly in `localStorage`.

Verified: forged cookies are rejected and re-issued, and after deletion the old
cookie resolves to a brand-new empty session.

---

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
cd api && .venv/Scripts/python -m pytest          # 82 tests, no database needed
.venv/Scripts/python -m pytest -m live            # hits real Orizn; needs a key

# Module self-checks — pure logic, no network
.venv/Scripts/python -m app.matching.filters      # the R0–R5 ladder
.venv/Scripts/python -m app.cache                 # key addressing
.venv/Scripts/python -m app.grading               # grade conversion
.venv/Scripts/python -m app.visa_readiness        # evidence parsers
```

---

## Decisions worth knowing

**The API is proxied same-origin.** `next.config.ts` rewrites `/api/*` to the
backend. This is not tidiness — the session cookie is `HttpOnly; SameSite=Lax`,
and browsers do not send Lax cookies on cross-site fetches. Point the browser
at another domain and every request mints a fresh empty session. Chosen over
`SameSite=None` because it keeps the cookie first-party and removes the need
for CORS entirely. It is also what forces the rate limiter to be proxy-aware.

**Grade conversion is per-country and piecewise.** `percentage / 100 * 4` is
wrong in the direction that hurts students: 62% is a First Division in Pakistan
(~3.3) and a D in the US (~1.0), and German grades run backwards (1.0 best), so
a linear map inverts the ranking. Every conversion carries a confidence, and
low-confidence OCR GPAs get tolerance at R0 so a scan artefact cannot silently
hide an eligible scholarship.

**RAG answers without resolvable citations are discarded.** Not flagged —
dropped. A student can act on an uncited visa instruction and lose a fee or a
semester.

**`last_verified_at` is serialised as explicit ISO-8601.** `str(datetime)`
emits a space separator that Safari refuses in `new Date()`; the freshness
badge would have read "Invalid Date" for a slice of users and nothing else
would have noticed.

---

## Known gaps

- **No Alembic.** `Base.metadata.create_all` runs on startup, which creates
  missing *tables* but never missing *columns* — so schema changes need hand-
  written `ALTER TABLE` against Neon. Fine while the schema moves; this is the
  first thing to fix under live rows.
- **Match Score is not decomposable.** PRD §10 specifies a weighted 0–100 score
  with a factor breakdown and a reproducible `score_version`. What ships is a
  single opaque LLM judgement plus prose. It is labelled "not an eligibility
  decision" and never presented as an acceptance probability, but §19's
  "reproducible score version and factor breakdown" is not met.
- **No link-health checking.** PRD §5.3 wants application URLs verified and
  4xx/5xx classified. Nothing checks, so "a 404 is not labelled closed" is
  currently true only because nothing can label it.
- **Unknown requirements pass silently.** PRD §6.2 wants them surfaced as
  "Verify eligibility". Today an unstated GPA or age simply does not filter.
- **Field-of-study inference is keyword matching**, so untagged programmes are
  not field-filtered and appear for everyone. Untagged is deliberately safer
  than mis-tagged, but a real taxonomy would beat it.
- **DAAD publishes no fixed deadlines** ("updated annually in the second
  quarter"), so those rows carry a note instead of a date. Not a parser bug —
  the date genuinely is not on the page.
- **Orizn's free plan is capped** and licensed for non-commercial evaluation
  only. `--repair-evidence` rebuilds the structured cache from the existing
  corpus at no quota cost.
