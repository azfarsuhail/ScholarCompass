"""Deterministic eligibility: the R0-R5 constraint-relaxation ladder.

No model runs in this file. If a student is ineligible, they are ineligible,
and nothing downstream is allowed to argue.

The ladder
----------
R0  exact      every stated constraint holds
R1  funding    accept partial/tuition when the student wanted full funding
R2  language   waive the language minimum (a test is retakeable in weeks)
R3  gpa        allow a 0.3 shortfall ("normally 3.0" is usually soft)
R4  deadline   include deadlines closed within the last year, for next cycle
R5  field      drop the field-of-study match — broad discovery

Ordered by how much the student would have to change, cheapest first. GPA
relaxes before deadline on purpose: a 2.9-against-3.0 near miss that is still
open beats a perfect fit that closed last month.

NEVER relaxed, at any rung
--------------------------
  * excluded_nationalities / eligible_nationalities. If a scholarship bars
    your passport, no rung makes you eligible, and showing it would cost a
    student a real application fee.
  * degree level.
  * A passed deadline, at R0-R3. Only R4 reintroduces closed calls, and they
    are labelled closed. Presenting a closed opportunity as live is the worst
    thing this product could do.

This is a pure function over plain dicts so the ladder can be tested without a
database — it is the logic most likely to be quietly wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

LEVELS = ("R0", "R1", "R2", "R3", "R4", "R5")

GPA_SLACK = 0.3
# How far back R4 looks for calls expected to reopen.
REOPEN_WINDOW = timedelta(days=365)
# Applied when the GPA came from OCR rather than the student's own typing.
# Without it, a scanning artefact silently drops eligible scholarships.
LOW_CONFIDENCE_GPA_TOLERANCE = 0.3
CONFIDENCE_FLOOR = 0.7


@dataclass
class Candidate:
    scholarship: dict
    level: str
    gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_exact(self) -> bool:
        return self.level == "R0"


def _gpa_tolerance(profile: dict) -> float:
    """Slack to forgive an uncertain GPA reading, not a weak student."""
    if profile.get("gpa_source") != "ocr":
        return 0.0
    conf = profile.get("gpa_confidence")
    if isinstance(conf, (int, float)) and conf < CONFIDENCE_FLOOR:
        return LOW_CONFIDENCE_GPA_TOLERANCE
    return 0.0


def _nationality_ok(s: dict, passport: str | None) -> bool:
    """Hard gate. Unknown passport is treated as eligible, not as excluded."""
    if not passport:
        return True
    p = passport.upper()
    if p in {x.upper() for x in (s.get("excluded_nationalities") or [])}:
        return False
    eligible = {x.upper() for x in (s.get("eligible_nationalities") or [])}
    # Empty list means open to all — it is not an empty whitelist.
    return not eligible or p in eligible


def _degree_ok(s: dict, want: str | None) -> bool:
    if not want:
        return True
    levels = {x.lower() for x in (s.get("degree_levels") or [])}
    return not levels or want.lower() in levels


def _deadline_open(s: dict, today: date) -> bool:
    if s.get("is_rolling"):
        return True
    d = s.get("deadline")
    # No stated deadline is "not stated", not "expired".
    return True if d is None else d >= today


def _language_ok(s: dict, profile: dict) -> bool:
    required = s.get("min_language_score") or {}
    if not required:
        return True
    have = profile.get("language_scores") or {}
    for test, minimum in required.items():
        got = have.get(test)
        if got is not None and got >= minimum:
            return True
    return False


def _field_ok(s: dict, profile: dict) -> bool:
    want = {f.lower() for f in (profile.get("fields_of_study") or []) if f}
    if not want:
        return True
    have = {f.lower() for f in (s.get("fields_of_study") or [])}
    if not have:
        return True
    # Substring both ways so "computer science" matches "computer science, ai".
    return any(w in h or h in w for w in want for h in have)


def _gpa_ok(s: dict, profile: dict, slack: float) -> bool:
    minimum = s.get("min_gpa_4")
    if minimum is None:  # not stated -> not a barrier
        return True
    gpa = profile.get("gpa_4")
    if gpa is None:  # unknown -> do not reject on a value we never had
        return True
    return float(gpa) >= float(minimum) - slack


def _age_ok(s: dict, profile: dict) -> bool:
    cap, age = s.get("max_age"), profile.get("age")
    if cap is None or age is None:
        return True
    return int(age) <= int(cap)


def _funding_ok(s: dict, profile: dict) -> bool:
    want = profile.get("funding_preference")
    if not want or want == "any":
        return True
    return (s.get("funding_type") or "full") == want


def _passes(s: dict, profile: dict, level: str, today: date) -> tuple[bool, list[str], list[str]]:
    """Evaluate one scholarship at one rung. Returns (ok, gaps, notes)."""
    rung = LEVELS.index(level)
    gaps: list[str] = []
    notes: list[str] = []

    # --- hard gates, identical at every rung ---
    if not _nationality_ok(s, profile.get("passport_iso3")):
        return False, [], []
    if not _degree_ok(s, profile.get("degree_level")):
        return False, [], []

    tol = _gpa_tolerance(profile)
    if tol:
        notes.append("Based on a GPA we read from your transcript — please confirm it.")

    # --- deadline: only R4+ may include closed calls ---
    if not _deadline_open(s, today):
        if rung < LEVELS.index("R4"):
            return False, [], []
        d = s.get("deadline")
        if d is None or d < today - REOPEN_WINDOW:
            return False, [], []
        gaps.append("This round has closed — shown so you can prepare for the next cycle.")

    # --- funding: R1+ accepts less than the student asked for ---
    if not _funding_ok(s, profile):
        if rung < LEVELS.index("R1"):
            return False, [], []
        gaps.append(f"Funding is {s.get('funding_type') or 'unspecified'}, not full.")

    # --- language: R2+ waives it ---
    if not _language_ok(s, profile):
        if rung < LEVELS.index("R2"):
            return False, [], []
        req = ", ".join(f"{k.upper()} {v}" for k, v in (s.get("min_language_score") or {}).items())
        gaps.append(f"Needs a language score you have not entered ({req}).")

    # --- gpa: R3+ forgives a small shortfall ---
    if not _gpa_ok(s, profile, tol):
        if rung < LEVELS.index("R3"):
            return False, [], []
        if not _gpa_ok(s, profile, tol + GPA_SLACK):
            return False, [], []
        gaps.append(
            f"Asks for {s.get('min_gpa_4')} GPA; you are slightly under. "
            "Stated minima are often soft — worth asking."
        )

    # --- age is a hard cap wherever it is stated ---
    if not _age_ok(s, profile):
        return False, [], []

    # --- field: R5 drops it ---
    if not _field_ok(s, profile):
        if rung < LEVELS.index("R5"):
            return False, [], []
        gaps.append("Outside the fields you listed.")

    return True, gaps, notes


def relax(
    profile: dict,
    scholarships: list[dict],
    *,
    min_results: int = 12,
    max_results: int = 40,
    today: date | None = None,
) -> tuple[list[Candidate], dict[str, int], str]:
    """Walk the ladder until there are enough results.

    Returns (candidates, per-level counts, deepest level reached). Each
    candidate is tagged with the FIRST rung that admitted it, so an exact match
    is never relabelled as a stretch just because a later rung also ran.
    """
    today = today or date.today()
    seen: set[str] = set()
    out: list[Candidate] = []
    counts: dict[str, int] = {}
    deepest = "R0"

    for level in LEVELS:
        found = 0
        for s in scholarships:
            key = s.get("slug") or str(s.get("id"))
            if key in seen:
                continue
            ok, gaps, notes = _passes(s, profile, level, today)
            if not ok:
                continue
            seen.add(key)
            out.append(Candidate(scholarship=s, level=level, gaps=gaps, notes=notes))
            found += 1
        counts[level] = found
        # `deepest` is the deepest rung that actually CONTRIBUTED a candidate,
        # not the last rung executed. With a small corpus the loop runs to R5
        # simply because it never reaches min_results -- reporting that as
        # "we relaxed to R5" would tell the student we widened their search
        # when in fact every result was an exact match.
        if found:
            deepest = level

        # Enough already? Stop — do not dilute good matches with stretches.
        if len(out) >= min_results:
            break

    # Exact matches first, then by deadline urgency. A stretch never outranks
    # an exact match regardless of how attractive it looks.
    out.sort(key=lambda c: (LEVELS.index(c.level), c.scholarship.get("deadline") or date.max))
    return out[:max_results], counts, deepest


def _demo() -> None:
    """Self-check. No database, no network."""
    base = {
        "slug": "x", "title": "X", "degree_levels": ["master"],
        "fields_of_study": ["engineering"], "min_gpa_4": 3.0,
        "min_language_score": {"ielts": 6.5}, "eligible_nationalities": [],
        "excluded_nationalities": [], "max_age": 35, "funding_type": "full",
        "deadline": date(2027, 1, 1), "is_rolling": False,
    }
    student = {
        "passport_iso3": "PAK", "degree_level": "master",
        "fields_of_study": ["engineering"], "gpa_4": 3.2,
        "language_scores": {"ielts": 7.0}, "age": 24,
        "funding_preference": "full",
    }
    today = date(2026, 9, 12)

    # Perfect fit lands at R0.
    got, _, _ = relax(student, [base], today=today)
    assert got[0].level == "R0", got

    # An explicit exclusion is never relaxed, not even at R5.
    barred = base | {"slug": "barred", "excluded_nationalities": ["PAK"]}
    got, _, _ = relax(student, [barred], today=today)
    assert got == [], "excluded nationality must never appear"

    # A whitelist that omits the student is equally absolute.
    wl = base | {"slug": "wl", "eligible_nationalities": ["IND"]}
    assert relax(student, [wl], today=today)[0] == []

    # Degree level is never relaxed either.
    phd = base | {"slug": "phd", "degree_levels": ["phd"]}
    assert relax(student, [phd], today=today)[0] == []

    # A closed deadline must NOT appear before R4...
    closed = base | {"slug": "closed", "deadline": date(2026, 3, 1)}
    cands, counts, _ = relax(student, [closed], today=today)
    assert cands and cands[0].level == "R4", cands
    assert counts.get("R0", 0) == 0, "closed call leaked into R0"
    assert any("closed" in g.lower() for g in cands[0].gaps)

    # ...and a long-dead call never appears at all.
    ancient = base | {"slug": "ancient", "deadline": date(2019, 1, 1)}
    assert relax(student, [ancient], today=today)[0] == []

    # Missing language score surfaces at R2, not R0.
    nolang = {k: v for k, v in student.items() if k != "language_scores"}
    cands, _, _ = relax(nolang, [base], today=today)
    assert cands[0].level == "R2", cands

    # GPA shortfall of 0.2 surfaces at R3; a 1.5 shortfall never does.
    weak = student | {"gpa_4": 2.85}
    assert relax(weak, [base], today=today)[0][0].level == "R3"
    assert relax(student | {"gpa_4": 1.5}, [base], today=today)[0] == []

    # A low-confidence OCR GPA gets tolerance, so a scan artefact does not
    # silently drop an eligible scholarship at R0.
    ocr = student | {"gpa_4": 2.95, "gpa_source": "ocr", "gpa_confidence": 0.5}
    cands, _, _ = relax(ocr, [base], today=today)
    assert cands[0].level == "R0", cands
    assert any("confirm" in n.lower() for n in cands[0].notes)
    # The same GPA typed by the student is taken at face value -> R3.
    typed = student | {"gpa_4": 2.95, "gpa_source": "user"}
    assert relax(typed, [base], today=today)[0][0].level == "R3"

    # Unstated constraints must never act as barriers.
    vague = {"slug": "v", "title": "V", "degree_levels": [], "fields_of_study": [],
             "min_gpa_4": None, "min_language_score": {}, "eligible_nationalities": [],
             "excluded_nationalities": [], "max_age": None, "funding_type": "full",
             "deadline": None, "is_rolling": False}
    assert relax(student, [vague], today=today)[0][0].level == "R0"

    # Exact matches outrank stretches in the final ordering.
    mixed = [closed, base]
    ordered, _, _ = relax(student, mixed, today=today)
    assert ordered[0].level == "R0" and ordered[-1].level == "R4"

    # A candidate is tagged by the FIRST rung that admitted it, and appears once.
    slugs = [c.scholarship["slug"] for c in ordered]
    assert len(slugs) == len(set(slugs)), "candidate duplicated across rungs"

    # Plenty of exact matches -> never descend the ladder at all.
    many = [base | {"slug": f"s{i}"} for i in range(15)]
    _, counts, deepest = relax(student, many, today=today)
    assert deepest == "R0", deepest

    print("relaxation ladder self-check passed")


if __name__ == "__main__":
    _demo()
