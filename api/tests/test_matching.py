"""Eligibility invariants.

These are the tests that protect students from the two failure modes that
actually cost them money: being shown something they cannot apply for, and
being hidden from something they can.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import grading, ocr
from app.ingest import crawler
from app.matching.filters import relax

TODAY = date(2026, 9, 12)

BASE = {
    "slug": "base", "title": "Base", "degree_levels": ["master"],
    "fields_of_study": ["engineering"], "min_gpa_4": 3.0,
    "min_language_score": {"ielts": 6.5}, "eligible_nationalities": [],
    "excluded_nationalities": [], "max_age": 35, "funding_type": "full",
    "deadline": date(2027, 1, 1), "is_rolling": False,
}
STUDENT = {
    "passport_iso3": "PAK", "degree_level": "master",
    "fields_of_study": ["engineering"], "gpa_4": 3.2,
    "language_scores": {"ielts": 7.0}, "age": 24, "funding_preference": "full",
}


def levels(cands):
    return [c.level for c in cands]


def test_perfect_fit_is_exact():
    got, _, deepest = relax(STUDENT, [BASE], today=TODAY)
    assert levels(got) == ["R0"]
    assert deepest == "R0"


@pytest.mark.parametrize(
    "override",
    [
        {"excluded_nationalities": ["PAK"]},
        {"eligible_nationalities": ["IND"]},
        {"degree_levels": ["phd"]},
    ],
    ids=["explicitly-excluded", "not-on-whitelist", "wrong-degree-level"],
)
def test_hard_gates_are_never_relaxed(override):
    """No rung, including R5, may admit a student who is legally ineligible."""
    got, _, _ = relax(STUDENT, [BASE | override], today=TODAY)
    assert got == []


def test_closed_deadline_never_appears_as_open():
    closed = BASE | {"slug": "closed", "deadline": date(2026, 3, 1)}
    got, counts, _ = relax(STUDENT, [closed], today=TODAY)

    assert counts["R0"] == 0, "a closed call leaked into exact matches"
    assert levels(got) == ["R4"]
    assert any("closed" in g.lower() for g in got[0].gaps)


def test_long_expired_calls_are_dropped_entirely():
    ancient = BASE | {"slug": "old", "deadline": date(2019, 1, 1)}
    assert relax(STUDENT, [ancient], today=TODAY)[0] == []


def test_unstated_requirements_are_not_barriers():
    """NULL means 'not stated', never 'zero' or 'excluded'."""
    vague = BASE | {
        "slug": "vague", "min_gpa_4": None, "min_language_score": {},
        "max_age": None, "deadline": None, "degree_levels": [], "fields_of_study": [],
    }
    assert levels(relax(STUDENT, [vague], today=TODAY)[0]) == ["R0"]


def test_low_confidence_ocr_gpa_gets_tolerance():
    """A scan artefact must not silently hide an eligible scholarship."""
    scanned = STUDENT | {"gpa_4": 2.95, "gpa_source": "ocr", "gpa_confidence": 0.5}
    got, _, _ = relax(scanned, [BASE], today=TODAY)

    assert levels(got) == ["R0"]
    assert any("confirm" in n.lower() for n in got[0].notes)


def test_user_entered_gpa_is_taken_at_face_value():
    """The same number typed by the student gets no tolerance -- it drops to R3."""
    typed = STUDENT | {"gpa_4": 2.95, "gpa_source": "user"}
    assert levels(relax(typed, [BASE], today=TODAY)[0]) == ["R3"]


def test_far_below_minimum_is_still_rejected():
    assert relax(STUDENT | {"gpa_4": 1.5}, [BASE], today=TODAY)[0] == []


def test_exact_matches_outrank_stretches():
    stretch = BASE | {"slug": "stretch", "fields_of_study": ["law"]}
    got, _, _ = relax(STUDENT, [stretch, BASE], today=TODAY)
    assert got[0].level == "R0"
    assert got[-1].level == "R5"


def test_candidates_are_tagged_by_first_admitting_rung_and_never_duplicated():
    pool = [BASE | {"slug": f"s{i}"} for i in range(3)] + [
        BASE | {"slug": "partial", "funding_type": "partial"}
    ]
    got, _, _ = relax(STUDENT, pool, today=TODAY)
    slugs = [c.scholarship["slug"] for c in got]

    assert len(slugs) == len(set(slugs))
    assert next(c.level for c in got if c.scholarship["slug"] == "partial") == "R1"


def test_enough_exact_matches_means_no_relaxation():
    many = [BASE | {"slug": f"s{i}"} for i in range(15)]
    _, _, deepest = relax(STUDENT, many, today=TODAY)
    assert deepest == "R0"


# --- grading and OCR invariants -------------------------------------------

def test_percentage_meaning_is_country_specific():
    """The bug this whole table exists to prevent."""
    assert grading.normalize("83.6%", country="IN").gpa_4 == 4.0
    assert grading.normalize("83.6%", country="US").gpa_4 == 3.0


def test_german_scale_is_not_inverted():
    better = grading.normalize("1,3", scheme="de_1_5").gpa_4
    worse = grading.normalize("3.7", scheme="de_1_5").gpa_4
    assert better > worse


def test_indian_cgpa_is_not_naively_scaled():
    """6.5/10 is a First Division, not a 2.6."""
    assert grading.normalize("CGPA 6.5", country="IN").gpa_4 >= 3.0


def test_unparseable_grade_is_none_not_zero():
    result = grading.normalize("see attached sheet")
    assert result.gpa_4 is None
    assert result.confidence == 0.0


def test_roll_number_is_not_mistaken_for_a_grade():
    text = "Roll No 123456 Session 2024 Total Marks Obtained 920/1100"
    grade = ocr.find_grade(text, country="PK")
    assert grade is not None
    assert 83 < grade.percentage < 84


# --- crawl escalation ------------------------------------------------------

def test_empty_spa_shell_escalates_to_browser():
    assert crawler.needs_js('<html><body><div id="root"></div></body></html>')


def test_server_rendered_page_does_not_waste_a_browser():
    html = '<div id="__next">' + ("Eligibility criteria for applicants. " * 40) + "</div>"
    assert not crawler.needs_js(html)
