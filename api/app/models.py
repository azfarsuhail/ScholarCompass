"""ScholarCompass persistence model.

Privacy posture (drives every table below):
  * No users table. Identity is an opaque, expiring AnonSession row.
  * Everything a student tells us hangs off that session and dies with it
    (ON DELETE CASCADE), so one DELETE erases the person entirely.
  * Reference data (Scholarship, VisaEvidence) is deliberately NOT
    session-scoped -- see VisaEvidence for why that is the safer choice.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Mirrors Orizn's `requirement` enum exactly (verified against the live API).
VISA_REQUIREMENTS = (
    "visa_free",
    "visa_required",
    "e_visa",
    "visa_on_arrival",
    "eta",
    "no_admission",
)

# Constraint-relaxation ladder. R0 = every hard filter applied.
RELAXATION_LEVELS = ("R0", "R1", "R2", "R3", "R4", "R5")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AnonSession(Base):
    """An anonymous, expiring bucket. The only 'identity' in the system."""

    __tablename__ = "anon_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Hard TTL. A sweeper deletes past this; cascades wipe the child rows.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Progressive profile: the student fills this in over time, never all at once.
    # JSONB because the shape genuinely varies by country/degree and we refuse
    # to normalise PII into queryable columns.
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Denormalised out of `profile` only because visa lookups filter on it.
    passport_iso3: Mapped[str | None] = mapped_column(String(3))

    documents: Mapped[list[Document]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    runs: Mapped[list[MatchRun]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Document(Base):
    """An uploaded transcript/certificate. We keep the extraction, not the file."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("anon_sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="transcript")
    filename: Mapped[str | None] = mapped_column(String(255))

    # Raw OCR text. The original upload is never written to disk or object
    # storage -- it is processed in-memory and discarded.
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))

    # Normalised grading output: {"scheme":"PK_HSSC","raw":"920/1100",
    #  "gpa_4":3.72,"percentage":83.6,"confidence":0.8}
    normalized: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[AnonSession] = relationship(back_populates="documents")


class Scholarship(Base):
    """Crawled opportunity. Public reference data -- not session-scoped."""

    __tablename__ = "scholarships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    host_country_iso3: Mapped[str | None] = mapped_column(String(3), index=True)

    # --- the hard deterministic filter columns (indexed, no LLM involved) ---
    degree_levels: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
    fields_of_study: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    min_gpa_4: Mapped[float | None] = mapped_column(Numeric(3, 2))
    min_language_score: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"ielts":6.5}
    # Empty array == open to all nationalities. Checked at R0..R4, dropped at R5.
    eligible_nationalities: Mapped[list[str]] = mapped_column(ARRAY(String(3)), default=list)
    excluded_nationalities: Mapped[list[str]] = mapped_column(ARRAY(String(3)), default=list)
    max_age: Mapped[int | None] = mapped_column(Integer)
    funding_type: Mapped[str | None] = mapped_column(String(16))  # full | partial | tuition
    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    is_rolling: Mapped[bool] = mapped_column(default=False)

    # --- flagship-programme gates -------------------------------------------
    # Chevening requires 2,800 hours of work experience and rejects outright
    # without it, so this is a real filter rather than a preference.
    min_work_experience_hours: Mapped[int | None] = mapped_column(Integer)
    # Chevening's two-year return rule, Fulbright's J-1 home-residency rule.
    # NEVER filtered on -- it does not affect eligibility, but a student must
    # know it before committing years of their life, so it is always shown.
    return_obligation: Mapped[str | None] = mapped_column(Text)
    # Prose entry requirement (e.g. Fulbright's "bachelor's equivalent").
    # Shown, not parsed: encoding it as a filter would need a degree-
    # equivalence table we do not have and would guess wrong.
    entry_requirement: Mapped[str | None] = mapped_column(Text)

    # Bare domain (ox.ac.uk, chevening.org) used to hotlink a provider logo
    # from Brandfetch's CDN. Stored as a domain, never as an image: the 512MB
    # container has no business holding binary assets.
    provider_domain: Mapped[str | None] = mapped_column(String(120))

    source_url: Mapped[str] = mapped_column(Text)
    # Continuous verification: how fresh is this row, and did JS rendering
    # (Playwright) produce it or a plain HTTP fetch?
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetch_strategy: Mapped[str | None] = mapped_column(String(16))  # http | playwright
    content_hash: Mapped[str | None] = mapped_column(String(64))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        CheckConstraint("min_gpa_4 IS NULL OR (min_gpa_4 >= 0 AND min_gpa_4 <= 4)", name="ck_gpa4"),
        Index("ix_scholarship_filter", "host_country_iso3", "deadline"),
    )


class MatchRun(Base):
    """One execution of the matching pipeline for one session."""

    __tablename__ = "match_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("anon_sessions.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(16), default="running")  # running|complete|failed
    # Deepest rung the ladder had to reach to fill the result set.
    relaxation_level: Mapped[str] = mapped_column(String(2), default="R0")
    # Per-rung candidate counts: {"R0":3,"R1":9,"R2":14} -- powers the
    # "we widened your search" disclosure in the UI.
    level_counts: Mapped[dict] = mapped_column(JSONB, default=dict)

    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    # Proves the <5s deterministic contract in production, not just in tests.
    deterministic_ms: Mapped[int | None] = mapped_column(Integer)
    enrichment_ms: Mapped[int | None] = mapped_column(Integer)

    # Snapshot of the profile used, so a run stays explainable after the
    # student edits their profile.
    profile_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[AnonSession] = relationship(back_populates="runs")
    explanations: Mapped[list[MatchExplanation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "relaxation_level IN ('R0','R1','R2','R3','R4','R5')", name="ck_relaxation_level"
        ),
    )


class MatchExplanation(Base):
    """The LLM's semantic verdict on one scholarship within one run.

    Split from MatchRun so deterministic results can stream immediately while
    these rows land asynchronously behind them.
    """

    __tablename__ = "match_explanations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), index=True
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scholarships.id", ondelete="CASCADE")
    )

    # Which rung admitted this candidate -- the UI labels R0 "exact match"
    # and R3+ "a stretch".
    entered_at_level: Mapped[str] = mapped_column(String(2), default="R0")
    deterministic_rank: Mapped[int | None] = mapped_column(Integer)

    semantic_score: Mapped[float | None] = mapped_column(Numeric(5, 2))  # 0-100
    rationale: Mapped[str | None] = mapped_column(Text)
    matched_criteria: Mapped[list] = mapped_column(JSONB, default=list)
    gaps: Mapped[list] = mapped_column(JSONB, default=list)

    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[MatchRun] = relationship(back_populates="explanations")

    __table_args__ = (
        UniqueConstraint("run_id", "scholarship_id", name="uq_run_scholarship"),
        CheckConstraint(
            "semantic_score IS NULL OR (semantic_score >= 0 AND semantic_score <= 100)",
            name="ck_semantic_score",
        ),
    )


class VisaEvidence(Base):
    """Cached, citation-bearing visa answer for a (passport, destination) pair.

    Deliberately NOT linked to a session. A passport+destination pair attached
    to a session id is a travel-intent record about a person; the same pair
    standing alone is public reference data. Keeping it global makes the cache
    useful to everyone AND removes the only row that could profile a student.
    """

    __tablename__ = "visa_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    passport_iso3: Mapped[str] = mapped_column(String(3))
    destination_iso3: Mapped[str] = mapped_column(String(3))

    # --- structured half: straight from Orizn ---
    requirement: Mapped[str | None] = mapped_column(String(24))
    visa_free_days: Mapped[int | None] = mapped_column(Integer)
    # Orizn's own verification date -- distinct from when WE fetched it.
    source_last_verified: Mapped[date | None] = mapped_column(Date)
    orizn_payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    # --- narrative half: RAG over official immigration sources ---
    summary: Mapped[str | None] = mapped_column(Text)
    # [{"quote":..., "url":..., "publisher":..., "retrieved_at":...}]
    # Never render `summary` without these; an uncited answer is a liability.
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    student_route_notes: Mapped[str | None] = mapped_column(Text)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        UniqueConstraint("passport_iso3", "destination_iso3", name="uq_visa_pair"),
        CheckConstraint(
            "requirement IS NULL OR requirement IN "
            "('visa_free','visa_required','e_visa','visa_on_arrival','eta','no_admission')",
            name="ck_visa_requirement",
        ),
    )


class VisaSourceChunk(Base):
    """Retrieval corpus for the visa RAG: chunks of official immigration pages.

    Retrieval is Postgres full-text search, not vectors. Groq has no embeddings
    endpoint and a local embedding model would not fit the 512MB container, but
    the deciding factor is that this corpus is small, highly structured and
    full of exact terms a student's question repeats verbatim ("X1 visa",
    "JW202", "residence permit"). Lexical search is genuinely strong on that
    shape of text -- vectors would be added weight for worse exact-term recall.

    ponytail: FTS + LLM rerank. Revisit only if recall measurably falls short.
    """

    __tablename__ = "visa_source_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    destination_iso3: Mapped[str] = mapped_column(String(3), index=True)
    # NULL means the page applies to all nationalities.
    passport_iso3: Mapped[str | None] = mapped_column(String(3), index=True)

    url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)

    # Generated in Postgres so the index can never drift from the content.
    search_vector = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title,'') || ' ' || content)", persisted=True),
    )

    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_visa_chunk_fts", "search_vector", postgresql_using="gin"),
        Index("ix_visa_chunk_pair", "destination_iso3", "passport_iso3"),
    )


class RetrievalCache(Base):
    """Content-addressed cache for anything expensive and deterministic.

    Two artifact types live here today:

      * ``match_score`` -- one Groq fit judgement. The key is a hash of the
        EXACT prompt (system + model + rendered user message), so the entry is
        content-addressed: change the prompt, the model, the profile or the
        scholarship and you get a different key rather than a stale answer.
        Re-running the same search therefore costs zero Groq calls, which is
        what keeps a demo (or a refresh-happy student) inside the quota.

      * ``deterministic`` -- one whole R0-R5 result set. Saves the Neon
        round-trip plus the ladder, which together are the entire latency
        budget of the first paint.

    Privacy: rows are NOT session-scoped, and that is a deliberate, bounded
    choice. A `match_score` hit requires a byte-identical prompt, and the
    prompt is built only from profile fields (never a name -- see
    routers/match.PROFILE_FIELDS, which does not accept one). So the only
    caller who can read an entry is one whose own profile already contains
    everything the cached text was derived from. Session-scoping it would make
    the cache almost never hit while protecting nothing extra.
    """

    __tablename__ = "retrieval_cache"

    # sha256 hex of the artifact's inputs. Not a surrogate id -- the key IS
    # the identity, which is what makes a stale read impossible by construction.
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(24), index=True)

    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Model + prompt version that produced it. Redundant with the key (both
    # are hashed in) but readable, so a bad generation can be found and purged.
    version: Mapped[str | None] = mapped_column(String(80))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
