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

from starlette.datastructures import Headers
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
