from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal, engine, get_db
from .models import AnonSession
from .session import COOKIE_NAME, SessionCookieMiddleware, current_session

SWEEP_INTERVAL_SECONDS = 900


async def _sweep_expired() -> None:
    """Delete expired sessions forever. Cascades take the documents and runs.

    This is the enforcement half of the privacy promise -- without it, 'ephemeral'
    is just a word in the README.
    """
    while True:
        try:
            async with SessionLocal() as db:
                await db.execute(
                    delete(AnonSession).where(
                        AnonSession.expires_at < datetime.now(timezone.utc)
                    )
                )
                await db.commit()
        except Exception:  # noqa: BLE001 - a failed sweep must never kill the app
            pass
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sweeper = asyncio.create_task(_sweep_expired())
    try:
        yield
    finally:
        sweeper.cancel()
        await engine.dispose()


app = FastAPI(
    title="ScholarCompass API",
    version="0.1.0",
    description="Anonymous scholarship + visa discovery. No accounts, ever.",
    lifespan=lifespan,
)

# Order matters: CORS is added last so it runs OUTERMOST, ensuring the
# Access-Control-* headers are present even on error responses.
app.add_middleware(SessionCookieMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_list,
    allow_credentials=True,  # required: the session cookie must cross origins
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/v1/session")
async def read_session(session: AnonSession = Depends(current_session)) -> dict:
    """Return the caller's own session. Minting happens transparently."""
    return {
        "session_id": str(session.id),
        "expires_at": session.expires_at.isoformat(),
        "profile": session.profile,
        "has_passport": session.passport_iso3 is not None,
    }


@app.delete("/v1/session", status_code=204)
async def forget_me(
    response: Response,
    session: AnonSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Erase everything tied to this session, right now.

    Not a soft delete and not a queued job -- the row is gone when this returns.
    """
    await db.delete(session)
    await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return Response(status_code=204)
