"""Visa integration tests, pinned against the real Orizn contract.

The headline case is PAK -> CHN, which is a genuine `visa_required` route.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.orizn import REQUIREMENT_LABELS, fetch_check

BASE = "https://visa.orizn.app/api/v1/visa/check"


@pytest.mark.asyncio
@respx.mock
async def test_pak_to_chn_is_visa_required(pak_chn_payload):
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=pak_chn_payload))

    check = await fetch_check("PAK", "CHN")

    assert route.called
    request = route.calls[0].request
    assert request.url.params["passport"] == "PAK"
    assert request.url.params["destination"] == "CHN"

    assert check is not None
    assert check.requirement == "visa_required"
    assert check.label == "Visa required"
    assert check.visa_free_days is None
    # The source's own verification date must survive parsing -- it is what we
    # show the student to justify trusting the answer.
    assert check.last_verified is not None
    assert check.last_verified.isoformat() == "2026-05-08"


@pytest.mark.asyncio
@respx.mock
async def test_requirement_enum_matches_orizn():
    """Every value Orizn can return must have a label, or the UI renders blank."""
    for requirement in (
        "visa_free", "visa_required", "e_visa",
        "visa_on_arrival", "eta", "no_admission",
    ):
        assert requirement in REQUIREMENT_LABELS
        assert REQUIREMENT_LABELS[requirement]


@pytest.mark.asyncio
@respx.mock
async def test_missing_api_key_degrades_rather_than_guessing():
    """A 401 must yield None, never a fabricated verdict."""
    respx.get(BASE).mock(return_value=httpx.Response(401, json={"error": "no key"}))
    assert await fetch_check("PAK", "CHN") is None


@pytest.mark.asyncio
@respx.mock
async def test_upstream_failure_is_not_an_exception():
    """A student mid-search must not see a 500 because a vendor blipped."""
    respx.get(BASE).mock(side_effect=httpx.ConnectTimeout("boom"))
    assert await fetch_check("PAK", "CHN") is None


@pytest.mark.asyncio
@respx.mock
async def test_unknown_pair_returns_none():
    respx.get(BASE).mock(return_value=httpx.Response(404, json={"error": "not found"}))
    assert await fetch_check("XXX", "CHN") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("passport,destination", [("pa", "CHN"), ("PAK", "C"), ("12A", "CHN")])
async def test_non_iso3_codes_are_rejected_before_the_network(passport, destination):
    with pytest.raises(ValueError):
        await fetch_check(passport, destination)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_pak_chn():
    """Hits the real API. Run with: pytest -m live (needs ORIZN_API_KEY).

    This is the dynamic check that the documented route still behaves as the
    product assumes -- exactly the Zhangjiajie (Hunan, CHN) planning case.
    """
    from app.config import settings

    if not settings().orizn_api_key:
        pytest.skip("ORIZN_API_KEY not configured")

    check = await fetch_check("PAK", "CHN")
    assert check is not None, "live Orizn lookup returned nothing"
    assert check.requirement in REQUIREMENT_LABELS
    # Pakistani passport holders need a visa for China. If this ever flips,
    # it is real news and the test should be updated deliberately.
    assert check.requirement == "visa_required"
