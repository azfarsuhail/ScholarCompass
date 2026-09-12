"""Orizn visa API client.

Contract verified against the live API (PAK->CHN returns visa_required with a
`last_verified` date). Notes that matter:

  * Auth is `x-api-key`. Keyless calls only work from an allow-listed Referer
    (their own site/localhost/extension), which a server container is not --
    so a missing key means degraded, not silent-wrong.
  * The free plan's response carries
    `license: "evaluation -- non-commercial use only"`. A paid plan is
    required before this ships commercially. Surfaced in the payload rather
    than buried, so the constraint is visible in the data.
  * `/visa/check` is the cheap yes/no. `/visa` is the 30-field version and
    needs a key with a real plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import VisaEvidence

log = logging.getLogger(__name__)

# Visa policy changes on the order of months, and Orizn stamps its own
# last_verified date, so a day of staleness is acceptable and saves quota.
CACHE_TTL = timedelta(hours=24)

REQUIREMENT_LABELS = {
    "visa_free": "No visa needed",
    "visa_required": "Visa required",
    "e_visa": "e-Visa available",
    "visa_on_arrival": "Visa on arrival",
    "eta": "Travel authorisation (ETA) required",
    "no_admission": "Entry not permitted",
}


@dataclass
class VisaCheck:
    passport: str
    destination: str
    requirement: str | None
    visa_free_days: int | None
    last_verified: date | None
    payload: dict
    stale: bool = False

    @property
    def label(self) -> str:
        return REQUIREMENT_LABELS.get(self.requirement or "", "Unknown")


def _iso3(v: str) -> str:
    v = (v or "").strip().upper()
    if len(v) != 3 or not v.isalpha():
        raise ValueError(f"expected an ISO 3166-1 alpha-3 code, got {v!r}")
    return v


async def fetch_check(passport: str, destination: str) -> VisaCheck | None:
    """Call GET /api/v1/visa/check. Returns None if the API is unusable."""
    p, d = _iso3(passport), _iso3(destination)
    headers = {"Accept": "application/json"}
    key = settings().orizn_api_key
    if key:
        headers["x-api-key"] = key

    url = f"{settings().orizn_base_url}/api/v1/visa/check"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as c:
            r = await c.get(url, params={"passport": p, "destination": d}, headers=headers)
        if r.status_code == 401:
            log.warning("orizn: no API key configured; visa lookups degraded")
            return None
        if r.status_code == 404:
            log.info("orizn: no data for %s->%s", p, d)
            return None
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("orizn lookup failed %s->%s: %s", p, d, e)
        return None

    lv = data.get("last_verified")
    try:
        verified = datetime.strptime(lv, "%Y-%m-%d").date() if lv else None
    except (TypeError, ValueError):
        verified = None

    return VisaCheck(
        passport=p,
        destination=d,
        requirement=data.get("requirement"),
        visa_free_days=data.get("visa_free_days"),
        last_verified=verified,
        payload=data,
    )


async def get_or_fetch(db: AsyncSession, passport: str, destination: str) -> VisaCheck | None:
    """Cache-through read of a (passport, destination) pair.

    On an upstream failure we deliberately return STALE cached data flagged as
    stale, rather than nothing. A student planning travel is better served by
    "this was true last week" than by an empty panel -- provided we say so.
    """
    p, d = _iso3(passport), _iso3(destination)
    now = datetime.now(timezone.utc)

    row = (
        await db.execute(
            select(VisaEvidence).where(
                VisaEvidence.passport_iso3 == p, VisaEvidence.destination_iso3 == d
            )
        )
    ).scalar_one_or_none()

    if row is not None and row.expires_at > now:
        return VisaCheck(p, d, row.requirement, row.visa_free_days,
                         row.source_last_verified, row.orizn_payload or {})

    fresh = await fetch_check(p, d)
    if fresh is None:
        if row is not None:
            return VisaCheck(p, d, row.requirement, row.visa_free_days,
                             row.source_last_verified, row.orizn_payload or {}, stale=True)
        return None

    if row is None:
        row = VisaEvidence(passport_iso3=p, destination_iso3=d)
        db.add(row)
    row.requirement = fresh.requirement
    row.visa_free_days = fresh.visa_free_days
    row.source_last_verified = fresh.last_verified
    row.orizn_payload = fresh.payload
    row.fetched_at = now
    row.expires_at = now + CACHE_TTL
    await db.commit()
    return fresh
