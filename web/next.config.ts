import type { NextConfig } from "next";

// Where the FastAPI container actually lives. In dev that is the local
// uvicorn; on Vercel it is the deployed backend origin.
// Trailing slashes are stripped because the destination below appends its own.
// A value pasted with one -- which is what a browser shows you when you copy a
// deployed URL, and what most dashboard fields keep -- produces
// `https://host//v1/documents`, and FastAPI 404s the double slash. That failure
// is nasty precisely because it looks like success: the proxy connects, the
// backend answers, and the only symptom is a 404 with the origin's own error
// body. Normalising here means the deploy cannot be broken by how someone
// typed a URL into a web form.
const API_ORIGIN = (process.env.API_ORIGIN ?? "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  /**
   * Proxy the API under our own origin.
   *
   * This is not a convenience — it is what makes the anonymous session work.
   * The session cookie is HttpOnly + SameSite=Lax. Lax cookies are NOT sent on
   * cross-site fetch/XHR, so if the browser called the backend on its own
   * domain directly, the cookie would never be attached and every request
   * would mint a fresh empty session.
   *
   * The alternative (SameSite=None; Secure) would work but deliberately opts
   * into cross-site cookie semantics for data we would rather keep first-party.
   * Rewriting keeps everything same-origin, and drops the need for CORS.
   */
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          // No account system means no third-party auth, analytics or embeds
          // to carve out. Nothing here needs camera, mic or geolocation.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), interest-cohort=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
