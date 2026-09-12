"""Postgres-backed cache for expensive, deterministic artifacts.

Neon rather than Redis, because the 512MB container already holds a Postgres
connection and adding a second datastore to a hackathon MVP buys nothing: the
hit rate we care about is across sessions and redeploys, which an in-process
dict would lose on both counts.

Two rules keep this honest:

  * Keys are content hashes of the inputs, never surrogate ids. A stale read is
    impossible by construction -- change any input and you address a different
    row instead of reading an out-of-date one.
  * Reads are batched. Forty per-candidate lookups against a network-attached
    database would cost more than the Groq calls they are meant to save, so
    `get_many` is one round-trip and the write piggybacks on a transaction the
    caller was already opening.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RetrievalCache

log = logging.getLogger(__name__)

# Bump when the SHAPE of a cached payload changes (a new field the reader
# requires). Changing the model or the prompt does NOT need a bump -- those are
# already inside the key.
SCHEMA_VERSION = "1"

MATCH_SCORE_TTL = timedelta(days=7)
# Short by design. The ladder's output embeds the catalogue as it was at write
# time, and ingest runs as a scheduled job, so a few minutes of staleness is
# invisible while a long TTL would outlive a re-crawl.
DETERMINISTIC_TTL = timedelta(minutes=15)


def key_for(*parts: object) -> str:
    """Content hash of the inputs that define an artifact."""
    blob = "\x1f".join(str(p) for p in (SCHEMA_VERSION, *parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def jsonable(value):
    """Round-trip through JSON so dates/UUIDs land in JSONB as strings.

    Note what this costs: a `date` comes back as "2027-01-01". That is fine for
    everything downstream (the SSE layer stringifies it identically, and the
    scoring prompt renders the same characters either way) but it means a
    cached scholarship dict must NEVER be fed back into matching/filters.py,
    which compares `deadline` as a real date. Cache the ladder's OUTPUT, not
    its input.
    """
    return json.loads(json.dumps(value, default=str))


async def get_many(db: AsyncSession, keys: list[str]) -> dict[str, dict]:
    """Fetch every live entry for these keys in ONE query."""
    if not keys:
        return {}
    try:
        rows = (
            await db.execute(
                select(RetrievalCache.cache_key, RetrievalCache.payload).where(
                    RetrievalCache.cache_key.in_(keys),
                    RetrievalCache.expires_at > datetime.now(timezone.utc),
                )
            )
        ).all()
    except Exception as e:  # noqa: BLE001 - a cache is never load-bearing
        log.warning("cache read failed, treating as a miss: %s", e)
        return {}
    return {k: v for k, v in rows if isinstance(v, dict)}


async def get(db: AsyncSession, key: str) -> dict | None:
    return (await get_many(db, [key])).get(key)


def put_stmt(key: str, artifact_type: str, payload: dict, ttl: timedelta, version: str = ""):
    """An upsert statement the caller adds to a transaction it already has.

    Returned rather than executed so writing a cache entry costs no extra
    round-trip -- see routers/match.py, where it rides along with the
    MatchExplanation insert that was happening anyway.
    """
    now = datetime.now(timezone.utc)
    values = {
        "cache_key": key,
        "artifact_type": artifact_type,
        "payload": jsonable(payload),
        "version": version[:80] or None,
        "expires_at": now + ttl,
    }
    return (
        insert(RetrievalCache)
        .values(**values)
        # A concurrent identical search should refresh the entry, not raise.
        .on_conflict_do_update(
            index_elements=[RetrievalCache.cache_key],
            set_={
                "payload": values["payload"],
                "version": values["version"],
                "expires_at": values["expires_at"],
            },
        )
    )


async def put(
    db: AsyncSession, key: str, artifact_type: str, payload: dict,
    ttl: timedelta, version: str = "",
) -> None:
    """Write one entry. Failure is logged and swallowed -- never load-bearing."""
    try:
        await db.execute(put_stmt(key, artifact_type, payload, ttl, version))
        await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("cache write failed: %s", e)
        await db.rollback()


async def sweep(db: AsyncSession) -> None:
    """Delete expired entries. Called from the session sweeper in main.py."""
    await db.execute(
        delete(RetrievalCache).where(RetrievalCache.expires_at < datetime.now(timezone.utc))
    )


def _demo() -> None:
    """Self-check. No database, no network."""
    from datetime import date

    # Identical inputs address the same row; any change addresses a new one.
    assert key_for("a", "b") == key_for("a", "b")
    assert key_for("a", "b") != key_for("a", "c")
    assert key_for("ab", "c") != key_for("a", "bc"), "separator must not collide"
    assert len(key_for("a")) == 64

    # Dates survive as the same characters the SSE layer would emit, which is
    # what keeps a prompt hash stable across a deterministic cache hit.
    payload = {"deadline": date(2027, 1, 1), "n": 3, "nested": [{"d": date(2026, 5, 4)}]}
    out = jsonable(payload)
    assert out["deadline"] == "2027-01-01" == str(payload["deadline"])
    assert out["nested"][0]["d"] == "2026-05-04"
    assert json.dumps(out)  # must be storable in JSONB

    print("cache self-check passed")


if __name__ == "__main__":
    _demo()
