import { api } from "@/lib/api";

export type VisaReadiness = {
  documents: string[];
  /** A derived view of `documents`, not a separate claim. */
  financial: string[];
  process: string[];
  passport_validity_months: number | null;
  /** The publisher's own verification date. Often null. */
  source_last_verified: string | null;
  /** When WE fetched it. Never present this as a verification date. */
  retrieved_at: string | null;
  sources: { url: string; publisher: string | null }[];
};

export type VisaCheck = {
  passport: string;
  destination: string;
  requirement: string | null;
  label: string;
  visa_free_days: number | null;
  available: boolean;
  stale?: boolean;
  message?: string;
  readiness?: VisaReadiness;
};

/**
 * Per-destination cache, shared across cards.
 *
 * A results page routinely shows several programmes in the same country, and
 * the answer depends only on (passport, destination) — the passport comes from
 * the session cookie. Without this, expanding five German scholarships would
 * fire five identical requests against a rate-limited upstream.
 *
 * Promises are cached, not just results, so two cards expanded in the same
 * tick share one in-flight request instead of racing.
 */
const cache = new Map<string, Promise<VisaCheck>>();

export function fetchVisaReadiness(destination: string): Promise<VisaCheck> {
  const key = destination.toUpperCase();
  const hit = cache.get(key);
  if (hit) return hit;

  const p = api<VisaCheck>(`/v1/visa/check?destination=${encodeURIComponent(key)}`).catch(
    (e) => {
      // Do not cache failures — a transient error should not poison the
      // destination for the rest of the session.
      cache.delete(key);
      throw e;
    },
  );
  cache.set(key, p);
  return p;
}

/** "12 Sep 2026" — or null, so callers can choose their own wording. */
export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
