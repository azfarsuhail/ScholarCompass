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


# --- refresh worker: date parsing and plan-gated field handling -------------

def test_verified_date_reads_both_field_names():
    """/check returns `last_verified`; /visa returns `last_verified_at`.

    Reading only the first is why every freshly-seeded row had a NULL
    verification date despite Orizn supplying one.
    """
    from app.ingest.visa_sources import _verified_date

    assert _verified_date({"last_verified": "2026-05-08"}).isoformat() == "2026-05-08"
    assert (
        _verified_date({"last_verified_at": "2026-05-10T13:37:46.882Z"}).isoformat()
        == "2026-05-10"
    )
    assert _verified_date({}) is None
    assert _verified_date({"last_verified": "not a date"}) is None


def test_upsell_stubs_are_never_stored_as_data():
    """Free-plan responses put an upsell STRING where the list should be.

    Joining a string iterates its characters, which would store
    "7; ; d; o; c..." as a document checklist.
    """
    from app.ingest.visa_sources import _compose

    stub = {
        "requirement": "visa_required",
        "documents_required": "7 documents — upgrade for full list",
        "process": "5 steps — upgrade for details",
    }
    titles = [c["title"] for c in _compose("PAK", "CHN", stub, "http://x")]
    assert not any("documents required" in t for t in titles)
    assert not any("application process" in t for t in titles)

    real = {
        "requirement": "visa_required",
        "documents_required": ["Valid passport", "Proof of sufficient funds"],
        "process": ["Apply", "Wait"],
    }
    titles = [c["title"] for c in _compose("PAK", "CHN", real, "http://x")]
    assert any("documents required" in t for t in titles)
    assert any("application process" in t for t in titles)


def test_zero_month_validity_gets_its_own_sentence():
    """0 is a real answer (the UK needs none beyond the stay), not missing data."""
    from app.ingest.visa_sources import _compose

    zero = _compose("PAK", "GBR", {"requirement": "visa_required",
                                   "passport_validity_months": 0}, "http://x")
    text = " ".join(c["content"] for c in zero)
    assert "at least 0 months" not in text
    assert "No passport validity is required" in text

    six = _compose("PAK", "CHN", {"requirement": "visa_required",
                                  "passport_validity_months": 6}, "http://x")
    assert "at least 6 months" in " ".join(c["content"] for c in six)


def test_fetch_classifies_failures():
    """429 ends the run; 5xx and transport errors are skipped past."""
    from app.ingest.visa_sources import Fetch

    assert Fetch(None, 429).quota_exhausted
    assert not Fetch(None, 429).transient
    assert Fetch(None, 500).transient
    assert Fetch(None, 503).transient
    assert Fetch(None, 0).transient
    assert not Fetch({"requirement": "visa_free"}, 200).transient
