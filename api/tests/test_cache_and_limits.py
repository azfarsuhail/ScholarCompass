"""Cache addressing and rate-limit bucketing.

Both are pure functions over plain data, so neither needs a database. Both are
also the kind of logic that fails silently rather than loudly -- a cache that
never hits still returns correct answers, and a rate limiter keyed on the wrong
thing still returns 429s. Hence tests.
"""

from __future__ import annotations

from datetime import date

from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from app.cache import jsonable, key_for
from app.limits import client_key
from app.matching.filters import Candidate
from app.matching.scoring import prompt_key

PROFILE = {
    "degree_level": "master",
    "fields_of_study": ["engineering"],
    "gpa_4": 3.2,
    "passport_iso3": "PAK",
    "skills": ["python"],
    "work_experience_hours": 3000,
}

SCHOLARSHIP = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "Example Award",
    "provider": "Example University",
    "host_country_iso3": "DEU",
    "degree_levels": ["master"],
    "fields_of_study": ["engineering"],
    "min_gpa_4": 3.0,
    "min_language_score": {"ielts": 6.5},
    "funding_type": "full",
    "deadline": date(2027, 1, 1),
    "max_age": 35,
}


def _candidate(scholarship: dict, gaps=None) -> Candidate:
    return Candidate(scholarship=scholarship, level="R0", gaps=gaps or [], notes=[])


# --- cache addressing -------------------------------------------------------


def test_prompt_key_survives_the_json_round_trip():
    """The property the whole score cache rests on.

    A deterministic cache HIT rebuilds candidates out of JSONB, which flattens
    `deadline` from a date to a string. If that changed the rendered prompt,
    every score would miss the cache on exactly the reruns the cache exists to
    make free -- and nothing would look broken, it would just be slow and
    expensive again.
    """
    fresh = _candidate(SCHOLARSHIP)
    from_cache = _candidate(jsonable(SCHOLARSHIP))
    assert prompt_key(PROFILE, fresh) == prompt_key(PROFILE, from_cache)


def test_prompt_key_changes_when_the_question_changes():
    base = prompt_key(PROFILE, _candidate(SCHOLARSHIP))

    # A different student.
    assert prompt_key(PROFILE | {"gpa_4": 2.9}, _candidate(SCHOLARSHIP)) != base
    # A different scholarship.
    assert prompt_key(PROFILE, _candidate(SCHOLARSHIP | {"title": "Other"})) != base
    # Same pair, but the deterministic gaps we hand the model differ, so the
    # answer would differ too.
    assert prompt_key(PROFILE, _candidate(SCHOLARSHIP, gaps=["Funding is partial."])) != base


def test_cache_keys_are_unambiguous():
    assert key_for("a", "b") == key_for("a", "b")
    assert key_for("ab", "c") != key_for("a", "bc"), "field separator collides"
    assert len(key_for("x")) == 64


def test_jsonable_preserves_the_characters_the_stream_would_emit():
    out = jsonable({"deadline": date(2027, 1, 1), "nested": [{"d": date(2026, 5, 4)}]})
    assert out["deadline"] == "2027-01-01"
    assert out["nested"][0]["d"] == "2026-05-04"


# --- rate-limit bucketing ---------------------------------------------------


def _request(headers: dict[str, str], client=("10.0.0.1", 5000)) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/v1/match/stream",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    })


def test_bucket_is_the_browser_not_the_proxy():
    """The bug this guards against would throttle every student as one caller.

    next.config.ts rewrites /api/* through the Next server, so `client.host` is
    always the proxy. Keying on it silently collapses everyone into a single
    5-per-minute bucket.
    """
    key = client_key(_request({"x-forwarded-for": "203.0.113.7, 70.1.1.1"}))
    assert key == "203.0.113.7"
    assert key != "10.0.0.1"


def test_two_students_behind_one_proxy_get_separate_buckets():
    a = client_key(_request({"x-forwarded-for": "203.0.113.7"}))
    b = client_key(_request({"x-forwarded-for": "198.51.100.2"}))
    assert a != b


def test_direct_connection_falls_back_to_the_socket_address():
    assert client_key(_request({})) == "10.0.0.1"
    # A blank or whitespace-only header must not become the bucket name.
    assert client_key(_request({"x-forwarded-for": "  , 198.51.100.9"})) == "198.51.100.9"
    assert client_key(_request({"x-forwarded-for": ""})) == "10.0.0.1"


def test_unknown_client_never_crashes_the_limiter():
    assert client_key(_request({}, client=None)) == "anonymous"


def test_the_limit_actually_fires_and_is_per_caller():
    """End-to-end over the real limiter, handler and decorator.

    Worth the TestClient: every piece of this wiring fails silently. A missing
    `app.state.limiter`, a renamed `request` parameter or an unregistered
    handler all leave a route that looks decorated and enforces nothing.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.limits import MATCH_STREAM_LIMIT, limiter, rate_limit_handler

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    @app.get("/probe")
    @limiter.limit(MATCH_STREAM_LIMIT)
    async def match_probe(request: Request):  # noqa: ARG001 - slowapi reads it by name
        return {"ok": True}

    client = TestClient(app)
    student = {"x-forwarded-for": "203.0.113.55"}

    for i in range(5):
        assert client.get("/probe", headers=student).status_code == 200, f"call {i + 1}"

    refused = client.get("/probe", headers=student)
    assert refused.status_code == 429
    # PRD 8.1: "return Retry-After when appropriate".
    assert refused.headers.get("Retry-After") == "60"
    assert "Too many searches" in refused.json()["detail"]

    # The point of keying on X-Forwarded-For: one heavy user must not lock out
    # everybody else behind the same proxy.
    other = {"x-forwarded-for": "198.51.100.77"}
    assert client.get("/probe", headers=other).status_code == 200


def test_visa_check_is_throttled_too():
    """The RAG explanation path spends the same Groq quota as the match stream."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.limits import VISA_CHECK_LIMIT, limiter, rate_limit_handler

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    @app.get("/probe-visa")
    @limiter.limit(VISA_CHECK_LIMIT)
    async def visa_probe(request: Request):  # noqa: ARG001 - slowapi reads it by name
        return {"ok": True}

    client = TestClient(app)
    student = {"x-forwarded-for": "203.0.113.90"}

    for i in range(10):
        assert client.get("/probe-visa", headers=student).status_code == 200, f"call {i + 1}"
    assert client.get("/probe-visa", headers=student).status_code == 429
