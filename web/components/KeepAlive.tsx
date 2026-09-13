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
export function KeepAlive() {
  useEffect(() => {
    const interval = setInterval(() => {
      fetch(`${process.env.NEXT_PUBLIC_API_URL}/docs`, { method: "GET" }).catch(
        () => {},
      );
    }, 840000); // 14 minutes

    return () => clearInterval(interval);
  }, []);

  return null;
}
