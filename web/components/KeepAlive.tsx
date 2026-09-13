"use client";

import { useEffect } from "react";

/**
 * Keeps the Render free-tier container warm while a tab is open.
 *
 * Renders nothing. Pings /docs rather than anything under /v1: the /v1 routes
 * carry slowapi limits keyed on the caller, and burning that budget on pings
 * would rate-limit the actual user. /docs is unlimited, and because it never
 * calls the `current_session` dependency it mints no session row per ping.
 *
 * GET, not HEAD: FastAPI's APIRoute does not add HEAD to a GET route the way
 * plain Starlette does, so HEAD against any of our routes is a 405.
 *
 * Requires NEXT_PUBLIC_API_URL. This is the one browser call that deliberately
 * goes direct to the backend origin instead of through the /api/* rewrite --
 * it carries no session cookie and wants none.
 */
// Read at module scope so the bundler inlines it. When the variable is absent
// at BUILD time the inline does not happen, `process.env.X` survives into the
// bundle, and in the browser it evaluates to undefined -- which template-literals
// into the string "undefined/docs" and resolves against the page origin. The
// result is a keep-alive that pings the FRONTEND's own 404 every ten minutes
// while the backend cold-starts exactly as before: alive-looking, warming
// nothing. Guarded below rather than left to fail silently.
const API_URL = process.env.NEXT_PUBLIC_API_URL;

const PING_INTERVAL_MS = 600_000; // 10 minutes

export function KeepAlive() {
  useEffect(() => {
    if (!API_URL) {
      console.warn(
        "KeepAlive: NEXT_PUBLIC_API_URL is unset, so no ping is sent and the " +
          "API container will cold-start. Set it in the deployment environment " +
          "and rebuild — it is inlined at build time, so adding it without a " +
          "redeploy changes nothing.",
      );
      return;
    }

    const interval = setInterval(() => {
      fetch(`${API_URL}/docs`, { method: "GET" }).catch(() => {});
    }, PING_INTERVAL_MS);

    return () => clearInterval(interval);
  }, []);

  return null;
}
