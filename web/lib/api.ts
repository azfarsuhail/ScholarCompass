/**
 * API client.
 *
 * `credentials: "include"` on every call is load-bearing: the anonymous
 * session lives in an HttpOnly cookie that JS cannot read or attach manually.
 * Omit it and every request silently mints a brand-new empty session.
 */

// Always same-origin. next.config.ts rewrites /api/* to the FastAPI origin,
// which is what lets the HttpOnly SameSite=Lax session cookie ride along.
export const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init.headers,
    },
  });

  if (!res.ok) {
    // Surface the server's own message when it sent one — a bare
    // "Request failed" is useless to a student staring at a broken upload.
    const detail = await res.text().catch(() => "");
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export type Session = {
  session_id: string;
  expires_at: string;
  profile: Record<string, unknown>;
  has_passport: boolean;
};

export const getSession = () => api<Session>("/v1/session");
export const forgetMe = () => api<void>("/v1/session", { method: "DELETE" });
