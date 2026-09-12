"""Semantic scoring. Runs only over candidates that already passed R0-R5.

The model's job is narrow and stated explicitly in the prompt: rank and
explain fit among options the student is ALREADY eligible for. It cannot add
a scholarship, cannot remove one, and its score never gates visibility -- a
candidate with a failed LLM call still renders, just without a rationale.

That split is the point of the whole architecture: eligibility is a database
question with a right answer, and "which of these suits you" is a judgement
call. Only the second one gets a model.
"""

from __future__ import annotations

import asyncio
import logging

from ..cache import key_for
from ..config import settings
from ..llm import complete_json

log = logging.getLogger(__name__)

SYSTEM = """You advise students on scholarship fit.

You will be given a student profile and ONE scholarship they are already
eligible for. Return JSON:
  {"score": 0-100, "rationale": "<=2 sentences, addressed to the student",
   "matched_criteria": ["..."], "gaps": ["..."]}

Rules:
- Score is fit, not eligibility. Eligibility is already settled.
- Be concrete: name the field, the country, the funding, the deadline.
- Never invent requirements that are not in the data you were given.
- If the data is thin, say so in the rationale and score conservatively.
- Do not promise outcomes, and do not tell the student they will be accepted."""

# Bounded so one slow candidate cannot hold the whole stream open.
PER_CANDIDATE_TIMEOUT = 12.0
MAX_CONCURRENCY = 5


def _profile_brief(profile: dict) -> str:
    bits = []
    for key, label in (
        ("degree_level", "Seeking"), ("fields_of_study", "Fields"),
        ("gpa_4", "GPA (4.0 scale)"), ("passport_iso3", "Passport"),
        ("age", "Age"), ("funding_preference", "Wants"),
        ("language_scores", "Language"), ("target_countries", "Prefers"),
        ("institution", "Studied at"), ("skills", "Skills"),
        ("work_experience_hours", "Work experience (hours)"),
    ):
        v = profile.get(key)
        if v:
            bits.append(f"{label}: {v}")
    # Roles spelled out rather than dumped as a dict repr -- fit is the one
    # thing the model IS here to judge, and this is the evidence for it.
    for e in (profile.get("experience") or [])[:5]:
        if isinstance(e, dict) and (e.get("role") or e.get("organisation")):
            period = f" ({e['period']})" if e.get("period") else ""
            bits.append(
                f"Experience: {e.get('role') or 'unspecified role'} at "
                f"{e.get('organisation') or 'unspecified organisation'}{period}"
            )
    if profile.get("gpa_source") == "ocr":
        bits.append("(GPA was read from a transcript scan and may be imprecise)")
    return "\n".join(bits) or "No profile details provided."


def _scholarship_brief(s: dict) -> str:
    return "\n".join(
        f"{k}: {s.get(k)}"
        for k in ("title", "provider", "host_country_iso3", "degree_levels",
                  "fields_of_study", "min_gpa_4", "min_language_score",
                  "funding_type", "deadline", "max_age")
        if s.get(k) not in (None, [], {})
    )


def _user_message(profile: dict, candidate) -> str:
    """The exact user turn sent to the model. Also the thing we cache on."""
    gaps = "\n".join(f"- {g}" for g in candidate.gaps)
    return (
        f"STUDENT\n{_profile_brief(profile)}\n\n"
        f"SCHOLARSHIP\n{_scholarship_brief(candidate.scholarship)}\n\n"
        f"KNOWN GAPS (already established, do not re-derive)\n{gaps or '- none'}"
    )


def prompt_key(profile: dict, candidate) -> str:
    """Cache key for one fit judgement.

    Hashes the WHOLE prompt, system text and model name included, so editing
    SYSTEM or switching models invalidates every stored score without anyone
    having to remember to bump a version constant. Built from the same
    `_user_message` the request itself uses, so the key cannot drift from what
    was actually asked.
    """
    return key_for("match_score", settings().match_model, SYSTEM, _user_message(profile, candidate))


async def score_one(profile: dict, candidate) -> dict | None:
    """Score a single candidate. None if the LLM is unavailable or too slow."""
    user = _user_message(profile, candidate)
    try:
        data = await asyncio.wait_for(
            # 400 tokens is enough for the answer but not for a reasoning
            # model's scratchpad, which shares the same budget.
            complete_json(SYSTEM, user, max_tokens=1600), timeout=PER_CANDIDATE_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.info("scoring timed out for %s", candidate.scholarship.get("slug"))
        return None
    if not isinstance(data, dict):
        return None

    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        score = 50.0
    return {
        "score": max(0.0, min(100.0, score)),
        "rationale": str(data.get("rationale") or "").strip()[:600],
        "matched_criteria": [str(x)[:160] for x in (data.get("matched_criteria") or [])][:6],
        # The deterministic gaps are authoritative; the model may only add to them.
        "gaps": candidate.gaps + [str(x)[:160] for x in (data.get("gaps") or [])][:6],
    }


async def score_stream(profile: dict, candidates: list, *, indices: list[int] | None = None):
    """Yield (index, scored) as each candidate finishes, not in input order.

    Streaming completion-order rather than input-order is what lets the UI
    animate each enrichment in as it lands, instead of stalling on the slowest.

    `indices` maps positions in `candidates` back to their position in the
    student's full result list. The caller passes it when it has already served
    some candidates from cache and is only asking the model about the misses --
    without it, the misses would be renumbered and land on the wrong cards.
    """
    idx = indices if indices is not None else list(range(len(candidates)))
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def run(i: int, cand):
        async with sem:
            return i, await score_one(profile, cand)

    tasks = [asyncio.create_task(run(idx[i], c)) for i, c in enumerate(candidates)]
    try:
        for coro in asyncio.as_completed(tasks):
            yield await coro
    finally:
        # If the client disconnects mid-stream, do not leave Groq calls running.
        for t in tasks:
            if not t.done():
                t.cancel()
