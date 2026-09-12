"""Extract a structured student profile from resume/transcript text.

This is the one place a model is allowed near profile data, and it is fenced in
hard:

  * It may only report what the document says. The prompt forbids inference,
    and every field defaults to null rather than to a plausible guess.
  * Its output is normalised and clamped here, then re-validated by the Zod
    schema on the client. A model that returns "3.37/4.0" or "Bachelors" must
    not be able to poison the form.
  * Nothing it produces is trusted as fact. The extracted profile lands in an
    EDITABLE form for the student to correct before matching runs -- the model
    fills the form in, it does not decide anything.

The shape returned here is the server half of the contract that
`web/lib/schema.ts` defines on the client. Keep the two in step.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .llm import complete_json

log = logging.getLogger(__name__)

DEGREE_LEVELS = ("bachelor", "master", "phd", "postdoc")

# Canonical field tags the matcher understands. The model is told to choose
# from this list rather than inventing labels, so extraction output can feed
# the same filter the catalogue is tagged against.
FIELD_TAGS = (
    "engineering", "computer science", "medicine", "economics", "public policy",
    "agriculture", "environment", "law", "physics", "chemistry", "biology",
    "arts and humanities", "education", "social sciences", "mathematics",
)

SYSTEM = f"""You extract a student profile from the text of a CV or transcript.

Return JSON with exactly these keys:
  full_name            string or null
  institution          string or null  (most recent/current institution)
  degree_level         one of {list(DEGREE_LEVELS)} or null
                       -- the degree they are studying for or just finished
  field_of_study       array of tags chosen ONLY from {list(FIELD_TAGS)}
  gpa_raw              string or null  (verbatim, e.g. "CGPA: 3.37" or "85%")
  graduation_year      integer or null
  skills               array of short strings, max 20
  experience           array of at most 5 objects:
                       {{"role": str, "organisation": str, "period": str or null}}
  languages            array of at most 5 strings (spoken/written languages)

Hard rules:
- Report ONLY what the document states. Never infer, complete or upgrade.
- If a field is absent, return null (or an empty array). Do not guess.
- Do NOT convert or rescale the GPA. Copy it verbatim into gpa_raw.
- degree_level is the level of study, not the subject. A "BS Computer Science"
  is "bachelor"; an "MSc" is "master".
- Copy organisation and role names exactly as written. Do not normalise,
  expand abbreviations, or substitute a similar company you know of."""


def _clean_str(v: Any, limit: int = 200) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s[:limit] if s else None


def _clean_list(v: Any, limit: int, item_len: int = 80) -> list[str]:
    if not isinstance(v, list):
        return []
    out = []
    for item in v:
        s = _clean_str(item, item_len)
        if s and s not in out:
            out.append(s)
    return out[:limit]


def parse_gpa_raw(raw: str | None, country: str | None = None) -> dict | None:
    """Normalise the verbatim grade using the existing per-country tables."""
    if not raw:
        return None
    # Imported here to keep this module importable without the grading tables
    # when only the LLM half is needed.
    from .grading import normalize

    result = normalize(raw, country=country)
    return result.as_dict() if result.gpa_4 is not None else None


def _coerce(data: dict, country: str | None) -> dict:
    """Clamp the model's output into the shape the client schema expects."""
    level = _clean_str(data.get("degree_level"), 20)
    level = level.lower() if level else None
    if level not in DEGREE_LEVELS:
        # A level we do not recognise is dropped rather than mapped to a
        # neighbour -- degree level is never relaxed by the matcher, so a wrong
        # value here silently hides every eligible scholarship.
        level = None

    fields = [f for f in _clean_list(data.get("field_of_study"), 6)
              if f.lower() in FIELD_TAGS]

    experience = []
    for item in (data.get("experience") or [])[:5]:
        if not isinstance(item, dict):
            continue
        role = _clean_str(item.get("role"), 120)
        org = _clean_str(item.get("organisation"), 120)
        if role or org:
            experience.append({
                "role": role or "",
                "organisation": org or "",
                "period": _clean_str(item.get("period"), 60),
            })

    year = data.get("graduation_year")
    if not isinstance(year, int) or not (1950 <= year <= 2100):
        year = None

    gpa_raw = _clean_str(data.get("gpa_raw"), 60)
    grade = parse_gpa_raw(gpa_raw, country)

    return {
        "full_name": _clean_str(data.get("full_name"), 120),
        "institution": _clean_str(data.get("institution"), 160),
        "degree_level": level,
        "field_of_study": [f.lower() for f in fields],
        "gpa_raw": gpa_raw,
        # Converted through the same per-country tables the matcher uses, so
        # the form shows the number matching will actually filter on.
        "gpa_4": grade["gpa_4"] if grade else None,
        "gpa_confidence": grade["confidence"] if grade else None,
        "graduation_year": year,
        "skills": _clean_list(data.get("skills"), 20, 40),
        "experience": experience,
        "languages": _clean_list(data.get("languages"), 5, 40),
    }


async def extract_profile(text: str, country: str | None = None) -> dict | None:
    """Extract a profile from document text. None if the LLM is unavailable."""
    if not text or len(text.strip()) < 80:
        return None

    data = await complete_json(
        SYSTEM,
        # Truncated: a CV's tail is projects and interests, and a longer prompt
        # buys nothing but latency and reasoning tokens.
        f"DOCUMENT TEXT\n{text[:8000]}",
        max_tokens=2600,
    )
    if not isinstance(data, dict):
        return None
    return _coerce(data, country)


def _demo() -> None:
    """Self-check for the clamping layer -- no network."""
    messy = {
        "full_name": "  Azfar Suhail ",
        "institution": "Institute of Business Management",
        "degree_level": "Bachelors",          # not in the enum
        "field_of_study": ["computer science", "underwater basket weaving"],
        "gpa_raw": "CGPA: 3.37",
        "graduation_year": 2027,
        "skills": ["FastAPI", "FastAPI", "Docker"],   # duplicate
        "experience": [{"role": "Streaming Intern", "organisation": "Tapmad"}],
        "languages": ["English"],
    }
    out = _coerce(messy, country="PK")

    # An unrecognised level is dropped, never mapped to a neighbour.
    assert out["degree_level"] is None, out["degree_level"]
    # Invented field tags are discarded.
    assert out["field_of_study"] == ["computer science"], out["field_of_study"]
    # Duplicates collapse.
    assert out["skills"] == ["FastAPI", "Docker"], out["skills"]
    # A 4.0-scale CGPA passes through unrescaled.
    assert out["gpa_4"] == 3.37, out["gpa_4"]
    assert out["full_name"] == "Azfar Suhail"
    assert out["experience"][0]["organisation"] == "Tapmad"

    # A valid level survives.
    assert _coerce({"degree_level": "bachelor"}, None)["degree_level"] == "bachelor"
    # Absent everything must not raise, and must not invent.
    empty = _coerce({}, None)
    assert empty["full_name"] is None and empty["skills"] == []
    assert empty["gpa_4"] is None
    # Out-of-range graduation years are rejected.
    assert _coerce({"graduation_year": 12027}, None)["graduation_year"] is None
    assert _coerce({"graduation_year": "soon"}, None)["graduation_year"] is None

    print("profile extraction clamp self-check passed")


if __name__ == "__main__":
    _demo()
