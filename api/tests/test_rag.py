"""RAG pipeline tests.

The pipeline's job is not to sound authoritative — it is to refuse to answer
without support. These tests exist because an uncited visa instruction is
worse than no answer: a student can act on it and lose a fee or a semester.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.rag import pipeline


class FakeChunk:
    def __init__(self, url, publisher, content, title=None):
        self.url = url
        self.publisher = publisher
        self.content = content
        self.title = title
        self.retrieved_at = datetime(2026, 9, 1, tzinfo=timezone.utc)


SOURCES = [
    FakeChunk(
        "https://www.visaforchina.cn/x1",
        "Chinese Visa Application Service Center",
        "Applicants for the X1 student visa must submit the JW202 form and an "
        "admission letter from the receiving institution.",
        "X1 Student Visa",
    ),
    FakeChunk(
        "https://www.nia.gov.cn/residence",
        "National Immigration Administration",
        "Holders of an X1 visa must apply for a residence permit within 30 days of entry.",
        "Residence Permit",
    ),
]


@pytest.fixture
def patched(monkeypatch):
    """Stub retrieval + LLM so the test pins pipeline behaviour, not vendors."""
    def set_llm(response):
        async def fake_complete_json(*a, **k):
            return response
        monkeypatch.setattr(pipeline, "complete_json", fake_complete_json)

    def set_sources(chunks):
        async def fake_retrieve(*a, **k):
            return chunks
        monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)

    return set_llm, set_sources


@pytest.mark.asyncio
async def test_cited_answer_resolves_source_urls(patched):
    set_llm, set_sources = patched
    set_sources(SOURCES)
    set_llm({
        "summary": "You need an X1 visa with a JW202 form.",
        "student_route_notes": "Apply for a residence permit within 30 days.",
        "citations": [
            {"n": 1, "quote": "must submit the JW202 form"},
            {"n": 2, "quote": "within 30 days of entry"},
        ],
    })

    out = await pipeline.answer(None, "PAK", "CHN")

    assert out is not None
    assert len(out["citations"]) == 2
    # Source numbers must resolve to the real URLs we supplied.
    assert out["citations"][0]["url"] == "https://www.visaforchina.cn/x1"
    assert out["citations"][1]["publisher"] == "National Immigration Administration"
    assert out["citations"][0]["retrieved_at"] is not None


@pytest.mark.asyncio
async def test_uncited_answer_is_discarded(patched):
    """A confident, source-free answer must not reach the student."""
    set_llm, set_sources = patched
    set_sources(SOURCES)
    set_llm({
        "summary": "You definitely do not need a visa, just fly over.",
        "student_route_notes": None,
        "citations": [],
    })

    assert await pipeline.answer(None, "PAK", "CHN") is None


@pytest.mark.asyncio
async def test_hallucinated_source_number_is_dropped(patched):
    """A citation pointing at a source we never supplied cannot be trusted."""
    set_llm, set_sources = patched
    set_sources(SOURCES)
    set_llm({
        "summary": "Fees are 2000 RMB.",
        "citations": [{"n": 7, "quote": "the fee is 2000 RMB"}],
    })

    # Every citation was fabricated, so nothing survives and the answer is dropped.
    assert await pipeline.answer(None, "PAK", "CHN") is None


@pytest.mark.asyncio
async def test_partially_hallucinated_citations_keep_only_real_ones(patched):
    set_llm, set_sources = patched
    set_sources(SOURCES)
    set_llm({
        "summary": "X1 visa needs a JW202.",
        "citations": [
            {"n": 1, "quote": "must submit the JW202 form"},
            {"n": 99, "quote": "invented"},
        ],
    })

    out = await pipeline.answer(None, "PAK", "CHN")
    assert out is not None
    assert len(out["citations"]) == 1
    assert out["citations"][0]["url"] == "https://www.visaforchina.cn/x1"


@pytest.mark.asyncio
async def test_no_sources_means_no_answer(patched):
    """Empty retrieval must not fall back to the model's own memory."""
    set_llm, set_sources = patched
    set_sources([])
    set_llm({"summary": "should never be used", "citations": [{"n": 1, "quote": "x"}]})

    assert await pipeline.answer(None, "PAK", "CHN") is None


@pytest.mark.asyncio
async def test_llm_unavailable_returns_none(patched):
    """No Groq key -> None, so the caller still shows the structured verdict."""
    set_llm, set_sources = patched
    set_sources(SOURCES)
    set_llm(None)

    assert await pipeline.answer(None, "PAK", "CHN") is None
