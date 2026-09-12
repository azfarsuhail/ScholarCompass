"""Anonymous session handling. There are no accounts -- this file is the
entire notion of 'who' in ScholarCompass.

The cookie carries a *signed* session UUID and nothing else. No profile data
ever rides in the cookie, so a stolen cookie is worth exactly one expiring
row, and tampering is rejected by the signature rather than silently trusted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import AnonSession

COOKIE_NAME = "sc_sid"
_SALT = "scholarcompass-anon-session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings().session_secret, salt=_SALT)


def sign(session_id: uuid.UUID) -> str:
    return _serializer().dumps(str(session_id))


def unsign(token: str) -> uuid.UUID | None:
    """Return the session id, or None if the token is forged/expired."""
    max_age = settings().session_ttl_hours * 3600
    try:
        return uuid.UUID(_serializer().loads(token, max_age=max_age))
    except (BadSignature, SignatureExpired, ValueError):
        return None


def _expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=settings().session_ttl_hours)


async def current_session(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AnonSession:
    """Resolve (or lazily mint) the caller's anonymous session.

    Minting is deferred to the response via `request.state.issue_sid` so that
    every route gets cookie handling for free -- see `SessionCookieMiddleware`.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        sid = unsign(token)
        if sid is not None:
            row = await db.get(AnonSession, sid)
            # A valid signature over a swept-away row is not an error; the
            # student simply gets a fresh, empty session.
            if row is not None and row.expires_at > datetime.now(timezone.utc):
                row.last_seen_at = datetime.now(timezone.utc)
                await db.commit()
                return row

    row = AnonSession(expires_at=_expiry())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    request.state.issue_sid = row.id
    return row


class SessionCookieMiddleware:
    """Writes the Set-Cookie header when a route minted a new session.

    Pure ASGI (not BaseHTTPMiddleware) because BaseHTTPMiddleware buffers the
    response body, which would break the SSE match stream in Phase 3.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                sid = state.get("issue_sid")
                if sid is not None:
                    cookie = (
                        f"{COOKIE_NAME}={sign(sid)}; "
                        f"Max-Age={settings().session_ttl_hours * 3600}; "
                        "Path=/; HttpOnly; SameSite=Lax"
                    )
                    if settings().cookie_secure:
                        cookie += "; Secure"
                    message.setdefault("headers", []).append(
                        (b"set-cookie", cookie.encode())
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
