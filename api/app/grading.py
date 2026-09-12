"""Normalise international grading schemes to a common GPA/4.0 scale.

Why this file is fussier than it looks
--------------------------------------
The tempting implementation is `gpa = percentage / 100 * 4`. It is wrong, and
wrong in the direction that hurts students, because a percentage does not mean
the same thing in two countries:

  * 62% from an Indian or Pakistani university is a solid First Division and
    converts to roughly a 3.3.
  * 62% from a US institution is a D, roughly a 1.0.
  * German grades run BACKWARDS -- 1.0 is the best grade and 4.0 is the bare
    pass -- so a linear map does not just distort the result, it inverts it.

So conversion is per-scheme and piecewise, using the anchor points registrars
and credential evaluators actually publish. Anything else quietly disqualifies
eligible students at the R0 filter, which is the one place we promised not to
be clever.

Every result carries a `confidence`. Grade conversion is genuinely lossy and
downstream code is expected to treat a low-confidence GPA as a hint, never as
grounds to hard-reject a candidate.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

GPA_MAX = 4.0


@dataclass(frozen=True)
class NormalizedGrade:
    scheme: str
    raw: str
    gpa_4: float | None
    percentage: float | None
    confidence: float  # 0..1
    note: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --- percentage -> GPA/4.0 anchors, per country ----------------------------
# Read as: (lower_bound_inclusive, gpa). Sorted high to low.
# Sources: standard credential-evaluation conversion bands.

_PCT_BANDS: dict[str, list[tuple[float, float]]] = {
    # South Asian marking is harsh; 60% is First Division, 80% is exceptional.
    "PK": [(80, 4.0), (70, 3.5), (65, 3.2), (60, 3.0), (55, 2.5), (50, 2.0), (40, 1.0), (0, 0.0)],
    "IN": [(80, 4.0), (70, 3.7), (60, 3.3), (55, 3.0), (50, 2.7), (45, 2.3), (40, 2.0), (0, 0.0)],
    "BD": [(80, 4.0), (70, 3.5), (60, 3.0), (50, 2.5), (40, 2.0), (0, 0.0)],
    "NG": [(70, 4.0), (60, 3.5), (50, 3.0), (45, 2.5), (40, 2.0), (0, 0.0)],
    # Chinese universities mark on a compressed 60-100 band.
    "CN": [(90, 4.0), (85, 3.7), (82, 3.3), (78, 3.0), (75, 2.7), (72, 2.3), (68, 2.0), (64, 1.5), (60, 1.0), (0, 0.0)],
    # US-style: 90+ is an A, below 60 fails.
    "US": [(93, 4.0), (90, 3.7), (87, 3.3), (83, 3.0), (80, 2.7), (77, 2.3), (73, 2.0), (70, 1.7), (67, 1.3), (60, 1.0), (0, 0.0)],
}
# Used when the issuing country is unknown. Deliberately the generous
# South-Asian-leaning curve, because under-converting is what rejects eligible
# students -- and it is paired with a low confidence so nothing hard-rejects.
_PCT_DEFAULT = _PCT_BANDS["IN"]


def _from_bands(value: float, bands: list[tuple[float, float]]) -> float:
    for lower, gpa in bands:
        if value >= lower:
            return gpa
    return 0.0


def percentage_to_gpa4(pct: float, country: str | None = None) -> tuple[float, float]:
    """Return (gpa_4, confidence)."""
    bands = _PCT_BANDS.get((country or "").upper(), _PCT_DEFAULT)
    known = (country or "").upper() in _PCT_BANDS
    return _from_bands(pct, bands), 0.85 if known else 0.55


# --- scheme-specific converters -------------------------------------------

def _german_to_gpa4(grade: float) -> float:
    """German 1.0 (best) .. 5.0 (fail). Inverted relative to GPA."""
    if grade > 4.0:
        return 0.0
    # 1.0 -> 4.0, 4.0 -> 1.0. Linear across the passing range.
    return round(max(0.0, min(GPA_MAX, 5.0 - grade)), 2)


def _france_20_to_gpa4(grade: float) -> float:
    """French /20. 16+ is rare and excellent; 10 is the pass mark."""
    return _from_bands(
        grade, [(16, 4.0), (14, 3.7), (12, 3.3), (10, 3.0), (8, 2.0), (0, 0.0)]
    )


def _uk_honours_to_gpa4(label: str) -> float | None:
    key = re.sub(r"[^a-z0-9]", "", label.lower())
    return {
        "first": 4.0, "1st": 4.0, "firstclass": 4.0,
        "21": 3.7, "upersecond": 3.7, "uppersecond": 3.7,
        "22": 3.0, "lowersecond": 3.0,
        "third": 2.3, "3rd": 2.3,
    }.get(key)


def _cgpa_10_to_gpa4(cgpa: float, country: str | None) -> tuple[float, float]:
    """Indian 10-point CGPA.

    Converted via percentage (the CBSE convention: percentage = CGPA * 9.5)
    rather than a flat cgpa/10*4, which would turn a 6.5 CGPA -- a genuine
    First Division at ~62% -- into a 2.6 and fail it against a 3.0 cutoff.
    """
    pct = cgpa * 9.5
    gpa, conf = percentage_to_gpa4(pct, country or "IN")
    return gpa, conf


# --- entry point -----------------------------------------------------------

def normalize(
    raw: str, scheme: str | None = None, country: str | None = None
) -> NormalizedGrade:
    """Normalise a free-text grade into GPA/4.0.

    `raw` is whatever OCR pulled off the transcript: "920/1100", "3.4/4",
    "CGPA 8.2", "First Class", "1,7", "78%".
    """
    text = (raw or "").strip()
    if not text:
        return NormalizedGrade("unknown", raw, None, None, 0.0, "empty input")

    cc = (country or "").upper() or None
    # European decimal comma: "1,7" is a German grade, not a thousands group.
    norm = re.sub(r"(?<=\d),(?=\d)", ".", text)

    # 1. "920/1100" or "3.4/4.0" -- an explicit fraction.
    frac = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", norm)
    if frac:
        got, total = float(frac.group(1)), float(frac.group(2))
        if total > 0 and got <= total:
            if total <= 5:  # already a GPA-style scale (x/4, x/5)
                gpa = round(got / total * GPA_MAX, 2)
                return NormalizedGrade(
                    scheme or f"gpa_{total:g}", raw, gpa, None, 0.9,
                    "rescaled from a GPA-style denominator",
                )
            pct = got / total * 100
            gpa, conf = percentage_to_gpa4(pct, cc)
            return NormalizedGrade(
                scheme or "marks_total", raw, gpa, round(pct, 2), conf,
                f"{got:g}/{total:g} = {pct:.1f}%"
                + ("" if cc in _PCT_BANDS else "; country unknown, used default band"),
            )

    # 2. Explicit percentage.
    pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", norm)
    if pct_m:
        pct = float(pct_m.group(1))
        if 0 <= pct <= 100:
            gpa, conf = percentage_to_gpa4(pct, cc)
            return NormalizedGrade(
                scheme or "percentage", raw, gpa, round(pct, 2), conf,
                None if cc in _PCT_BANDS else "country unknown, used default band",
            )

    # 3. UK honours classification.
    uk = _uk_honours_to_gpa4(text)
    if uk is not None:
        return NormalizedGrade("uk_honours", raw, uk, None, 0.8, None)

    # 4. Labelled CGPA / GPA.
    cg = re.search(r"(?:cgpa|gpa|sgpa)\D{0,6}(\d+(?:\.\d+)?)", norm, re.I)
    if cg:
        val = float(cg.group(1))
        if val <= 4.0:
            return NormalizedGrade(scheme or "gpa_4", raw, round(val, 2), None, 0.95, None)
        if val <= 5.0:
            return NormalizedGrade(
                scheme or "gpa_5", raw, round(val / 5 * GPA_MAX, 2), None, 0.85, None
            )
        if val <= 10.0:
            gpa, conf = _cgpa_10_to_gpa4(val, cc)
            return NormalizedGrade(
                scheme or "cgpa_10", raw, gpa, round(val * 9.5, 2), conf,
                "10-point CGPA via percentage (CGPA x 9.5)",
            )

    # 5. Scheme was told to us explicitly -- trust it over guessing.
    num = re.search(r"(\d+(?:\.\d+)?)", norm)
    if scheme and num:
        val = float(num.group(1))
        if scheme == "de_1_5":
            return NormalizedGrade(scheme, raw, _german_to_gpa4(val), None, 0.85,
                                   "German scale is inverted (1.0 best)")
        if scheme == "fr_20":
            return NormalizedGrade(scheme, raw, _france_20_to_gpa4(val), None, 0.8, None)

    # 6. Bare number, no scheme. Guess, but say so loudly via confidence.
    if num:
        val = float(num.group(1))
        if val <= 4.0:
            return NormalizedGrade("gpa_4?", raw, round(val, 2), None, 0.5,
                                   "assumed a 4.0 GPA; scheme not stated")
        if 40 <= val <= 100:
            gpa, conf = percentage_to_gpa4(val, cc)
            return NormalizedGrade("percentage?", raw, gpa, val, min(conf, 0.5),
                                   "assumed a percentage; scheme not stated")

    return NormalizedGrade("unknown", raw, None, None, 0.0, "could not parse a grade")


def _demo() -> None:
    """Self-check. Runs with `python -m app.grading`."""
    # A Pakistani HSSC result. Naive /100*4 would give 3.35 and is wrong-ish;
    # the real point is it must clear a 3.0 cutoff, which it does.
    pk = normalize("920/1100", country="PK")
    assert pk.percentage is not None and 83 < pk.percentage < 84, pk
    assert pk.gpa_4 == 4.0, pk

    # Same percentage, US scheme -> materially different GPA. This is the whole
    # reason the per-country tables exist.
    assert normalize("83.6%", country="US").gpa_4 == 3.0
    assert normalize("83.6%", country="IN").gpa_4 == 4.0

    # German inversion: 1.3 is excellent, 3.7 is weak. A linear map would
    # rank these backwards.
    good = normalize("1,3", scheme="de_1_5")
    weak = normalize("3.7", scheme="de_1_5")
    assert good.gpa_4 is not None and weak.gpa_4 is not None
    assert good.gpa_4 > weak.gpa_4, (good, weak)

    # Indian 10-point CGPA must not be read as cgpa/10*4.
    cg = normalize("CGPA 6.5", country="IN")
    assert cg.gpa_4 is not None and cg.gpa_4 >= 3.0, cg

    # Already-normalised GPAs pass through untouched.
    assert normalize("3.4/4.0").gpa_4 == 3.4
    assert normalize("GPA 3.85").gpa_4 == 3.85

    # UK classifications are ordered correctly.
    first = normalize("First Class").gpa_4
    lower = normalize("2:2").gpa_4
    assert first is not None and lower is not None and first > lower

    # Unparseable input fails loudly (confidence 0), never silently as 0.0 GPA.
    junk = normalize("see attached sheet")
    assert junk.gpa_4 is None and junk.confidence == 0.0, junk

    print("grading self-check passed")


if __name__ == "__main__":
    _demo()
