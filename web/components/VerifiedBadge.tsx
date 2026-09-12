"use client";

import { useSyncExternalStore } from "react";

/**
 * Freshness badge — PRD §5.2 ("Show Last Verified and stale/unverified state").
 *
 * Provenance is the claim this product is actually making, so the badge has to
 * be able to say an uncomfortable thing: not just "verified" but "we have not
 * re-checked this in a week" and "we never checked it at all". A badge that
 * only renders the good case is decoration, not evidence.
 *
 * DESIGN.md compliance:
 *  - Surface lift (surface-2) + ink-muted type, the documented treatment for
 *    meta information. Sky blue is reserved for links/focus/selection.
 *  - Success green appears as a GLYPH fill only ("Semantic > Success Green:
 *    Glyph fill, not surface"), never as a background.
 *  - Stale and unverified get no invented amber or red — DESIGN.md forbids a
 *    second accent family. They step DOWN to a hollow dot, and the text always
 *    carries the meaning, so nothing is encoded by colour alone.
 *  - rounded-sm (6px) is the documented badge radius; fr-micro the meta tier.
 */

/** PRD §5.2: an active scholarship listing should be re-verified within 48h. */
const FRESH_WINDOW_MS = 48 * 60 * 60 * 1000;

/**
 * The wall clock, read the way React wants a mutable external source read.
 *
 * `Date.now()` inline in the body is impure, and `setState` in an effect is
 * the other thing the compiler rejects. `useSyncExternalStore` is the
 * sanctioned third option — and it hands us a correct server snapshot for
 * free.
 *
 * The snapshot is bucketed to the MINUTE deliberately: a raw `Date.now()`
 * returns a new value on every call, which makes useSyncExternalStore re-render
 * forever. Freshness is measured in hours, so minute resolution is free.
 */
const NO_SUBSCRIBE = () => () => {};
const currentMinute = () => Math.floor(Date.now() / 60_000);
/** No clock before hydration — see the default-to-stale note below. */
const noClockYet = () => null;

export function VerifiedBadge({ at }: { at?: string | null }) {
  const parsed = at ? new Date(at) : null;
  // An unparseable timestamp is "unverified" — not a crash, and not a claim.
  const verifiedAt = parsed && !Number.isNaN(parsed.getTime()) ? parsed : null;
  const stamp = verifiedAt ? verifiedAt.getTime() : null;

  /**
   * Defaults to NOT fresh on purpose. Before hydration there is no clock, and
   * the right failure mode is under-claiming verification rather than
   * asserting a freshness we have not established. The visible label needs no
   * clock at all, so nothing shifts when the real value arrives.
   */
  const minute = useSyncExternalStore(NO_SUBSCRIBE, currentMinute, noClockYet);
  const fresh =
    stamp !== null && minute !== null && minute * 60_000 - stamp < FRESH_WINDOW_MS;

  const label = verifiedAt
    ? `Verified ${verifiedAt.toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      })}`
    : "Not verified";

  const title = verifiedAt
    ? `Last verified ${verifiedAt.toLocaleString()}${
        fresh ? "" : " — outside our 48-hour freshness target"
      }`
    : "We have not been able to re-check this listing against its source";

  return (
    <span
      title={title}
      className="fr-micro inline-flex shrink-0 items-center gap-xxs rounded-sm bg-surface-2 px-xs py-xxs text-ink-muted"
    >
      <span
        aria-hidden="true"
        className={
          fresh
            ? // Glyph fill, per DESIGN.md. Never a green surface.
              "size-1.5 rounded-full bg-success"
            : // Hollow: present, but deliberately not asserting freshness.
              "size-1.5 rounded-full border border-current"
        }
      />
      {label}
    </span>
  );
}
