"""Request body size guard.

Placement is the whole point of this file. Checking `len(await file.read())`
inside the handler is too late twice over:

  1. By the time a handler runs, Starlette has already parsed the entire
     multipart body. A 2GB upload is fully received before any handler-level
     check can fire -- which on a 512MB container is an OOM, not a 413.
  2. Starlette's UploadFile is a SpooledTemporaryFile: past ~1MB it rolls over
     to a real file on disk. So an unbounded upload also lands bytes on disk,
     which is not what "processed in memory and discarded" should mean.

So the limit is enforced here, before parsing: reject on Content-Length up
front, and count bytes during streaming to catch a chunked request that
declares no length at all.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse


class MaxBodySizeMiddleware:
    """Reject oversized request bodies before they are parsed or spooled."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        # A client can omit Content-Length (chunked transfer), so also count
        # what actually arrives and cut it off mid-stream.
        received = 0
        too_big = False

        async def counting_receive():
            nonlocal received, too_big
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_big = True
                    # Stop the stream rather than keep buffering the attack.
                    return {"type": "http.disconnect"}
            return message

        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counting_receive, guarded_send)
        if too_big and not started:
            await self._reject(send)

    async def _reject(self, send) -> None:
        limit_mb = self.max_bytes // (1024 * 1024)
        response = JSONResponse(
            {"detail": f"File is larger than {limit_mb}MB."}, status_code=413
        )
        await response({"type": "http"}, None, send)


# ---------------------------------------------------------------------------
# Anonymous abuse control
# ---------------------------------------------------------------------------
#
# There are no accounts, so there is no user to throttle -- only an address.
# The expensive path is /v1/match/stream: one call fans out to as many as 40
# Groq completions, which makes looping it the cheapest possible way for an
# anonymous caller to spend the whole monthly quota in a couple of minutes.
#
# Storage is slowapi's in-memory backend on purpose. It costs a dict of
# timestamps per address, which is the right trade at 512MB with a single
# uvicorn worker; the counters simply reset on redeploy. Redis would buy
# cross-container accuracy we have no containers to need yet.
#
# ponytail: in-memory counters, per-process. Move to Redis when there is more
# than one API container, not before.


def client_key(request: Request) -> str:
    """The bucket one caller is counted against.

    `request.client.host` would be WRONG here, and wrong in the worst
    direction: next.config.ts rewrites /api/* through the Next server, so every
    request reaches FastAPI from the proxy's address. Keying on it would put
    every student on the planet in ONE shared 5-per-minute bucket -- the second
    visitor of the minute would be throttled because of the first.

    The browser's own address is the first entry of X-Forwarded-For.

    Known limitation, stated plainly because the deployment topology changed
    under it: the backend is reachable directly on its own public hostname, not
    only through the proxy. Bot traffic in the origin logs proves it. So a
    caller who skips the frontend can spoof this header and mint a fresh bucket
    per request.

    That makes this limit a cost control against ordinary looping -- a refresh
    key held down, a demo re-run, a retry storm -- and NOT a security boundary
    against someone deliberately trying to burn the Groq quota. Closing that
    gap needs the origin to stop accepting unproxied traffic (a shared secret
    the rewrite injects, or network rules), after which this can go back to
    being trustworthy. Counting a trusted-hop offset instead would not help
    while the origin still answers anyone who asks.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    for hop in forwarded.split(","):
        candidate = hop.strip()
        if candidate:
            return candidate
    client = request.client
    return client.host if client else "anonymous"


# headers_enabled stays OFF. It adds informational X-RateLimit-* headers to
# SUCCESSFUL responses, but to do so slowapi reaches into the route's return
# value and raises "parameter `response` must be an instance of
# starlette.responses.Response" for any handler that returns a plain dict --
# i.e. every normal FastAPI route. That is a trap for whoever decorates the
# next endpoint, in exchange for headers an EventSource cannot read anyway.
# The header that actually matters, Retry-After on a 429, is set explicitly in
# rate_limit_handler below.
limiter = Limiter(key_func=client_key, headers_enabled=False)

# One search per twelve seconds, sustained. Comfortably above a student
# pressing "Search again" a few times, far below a loop.
MATCH_STREAM_LIMIT = "5/minute"

# /v1/visa/check spends the SAME Groq quota whenever `explain=true`, and the
# RAG model is the larger one. Looser than the match stream because the common
# case is a cheap indexed read that every result card fires on expand.
VISA_CHECK_LIMIT = "10/minute"


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 with a Retry-After, phrased for a student rather than an operator."""
    try:
        retry_after = int(exc.limit.limit.get_expiry())
    except Exception:  # noqa: BLE001 - never fail the error path over a header
        retry_after = 60
    return JSONResponse(
        {
            "detail": "Too many searches from this connection. "
                      f"Try again in about {retry_after} seconds.",
            "retry_after": retry_after,
        },
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )
