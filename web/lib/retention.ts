/**
 * How long session data lives, for UI copy.
 *
 * This exists because the copy drifted: the backend TTL moved to 7 days while
 * three pages still promised "72 hours". A privacy promise that contradicts
 * the actual retention window is the one kind of stale copy that really
 * matters, so it is read from an env var rather than typed into each page.
 *
 * Keep NEXT_PUBLIC_SESSION_TTL_HOURS equal to the API's SESSION_TTL_HOURS.
 */
const HOURS = Number(process.env.NEXT_PUBLIC_SESSION_TTL_HOURS ?? 168);

export const retentionHours = Number.isFinite(HOURS) && HOURS > 0 ? HOURS : 168;

export const retentionLabel =
  retentionHours % 24 === 0
    ? `${retentionHours / 24} ${retentionHours / 24 === 1 ? "day" : "days"}`
    : `${retentionHours} hours`;
