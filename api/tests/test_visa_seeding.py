"""Tests for turning an Orizn payload into RAG corpus chunks.

Runs against the real captured PAK->CHN payload, so the seeding logic is
verified without needing a live API key in CI.
"""

from __future__ import annotations

from app.ingest.visa_sources import PUBLISHER, _compose

SOURCE = "https://visa.orizn.app/api/v1/visa/check?passport=PAK&destination=CHN"


def test_pak_chn_produces_a_verdict_chunk(pak_chn_payload):
    chunks = _compose("PAK", "CHN", pak_chn_payload, SOURCE)

    assert chunks, "no chunks produced from a valid payload"
    verdict = chunks[0]
    assert "PAK" in verdict["content"] and "CHN" in verdict["content"]
    assert "Visa required" in verdict["content"]
    assert "visa_required" in verdict["content"]
    # The source's verification date must survive into the corpus — it is what
    # makes the eventual citation checkable.
    assert "2026-05-08" in verdict["content"]


def test_chunks_are_nationality_scoped(pak_chn_payload):
    """A chunk must never be retrievable for a different passport."""
    for c in _compose("PAK", "CHN", pak_chn_payload, SOURCE):
        assert c["passport_iso3"] == "PAK"
        assert c["destination_iso3"] == "CHN"


def test_every_chunk_carries_resolvable_provenance(pak_chn_payload):
    for c in _compose("PAK", "CHN", pak_chn_payload, SOURCE):
        assert c["url"] == SOURCE
        assert c["publisher"] == PUBLISHER
        assert c["retrieved_at"] is not None
        assert c["content"].strip()


def test_thin_free_plan_payload_still_yields_one_chunk(pak_chn_payload):
    """The free /check response has no documents or process fields."""
    chunks = _compose("PAK", "CHN", pak_chn_payload, SOURCE)
    titles = " ".join(c["title"] for c in chunks)
    assert "entry requirement" in titles
    # Nothing may be fabricated for fields the free plan does not return.
    assert "documents required" not in titles
    assert "application process" not in titles


def test_full_plan_payload_expands_into_topic_chunks():
    """A paid payload splits by topic so FTS ranks on-topic chunks first."""
    rich = {
        "requirement": "visa_required",
        "last_verified": "2026-05-08",
        "documents_required": ["Valid passport", "JW202 form", "Admission letter"],
        "process": ["Obtain JW202", "Apply at the visa centre", "Collect visa"],
        "passport_validity_months": 6,
        "embassy": {"visa_application_embassy": {"name": "Embassy of China", "city": "Islamabad"}},
    }
    chunks = _compose("PAK", "CHN", rich, SOURCE)
    titles = " ".join(c["title"] for c in chunks)

    assert "documents required" in titles
    assert "application process" in titles
    assert "passport validity" in titles
    assert "where to apply" in titles
    # Content must come from the payload, not from the model's imagination.
    joined = " ".join(c["content"] for c in chunks)
    assert "JW202" in joined
    assert "Islamabad" in joined


def test_visa_free_payload_records_allowed_days():
    payload = {"requirement": "visa_free", "visa_free_days": 90, "last_verified": "2026-05-08"}
    content = _compose("FRA", "JPN", payload, SOURCE)[0]["content"]

    assert "No visa needed" in content
    assert "90 days" in content


def test_study_caveat_is_always_present(pak_chn_payload):
    """An entry rule is not a student-visa rule, and must not read as one."""
    content = _compose("PAK", "CHN", pak_chn_payload, SOURCE)[0]["content"]
    assert "student visa" in content.lower()
    assert "residence permit" in content.lower()
