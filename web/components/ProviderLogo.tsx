"use client";

import { useState } from "react";

/**
 * Provider logo, hotlinked from Brandfetch's CDN.
 *
 * The image is fetched by the BROWSER, straight from Brandfetch's global CDN.
 * Nothing is proxied, cached or stored server-side — the 512MB API container
 * has no business holding binary assets, and this way the logos also cost it
 * zero bandwidth.
 *
 * Brandfetch requires a free client id and asks for no attribution badge.
 * Without one the CDN answers 403, so when the key is absent we do not even
 * attempt the request: a broken image icon on every card would look far worse
 * than the monogram below.
 */

const CLIENT_ID = process.env.NEXT_PUBLIC_BRANDFETCH_CLIENT_ID;

/** Deterministic tint per provider, so a card's logo colour is stable. */
// DESIGN.md forbids a second chromatic accent family, so the fallback marks
// identity by surface lift and ink level rather than by tinting each brand a
// different colour.
const TINTS = [
  "bg-surface-2 text-ink",
  "bg-surface-2 text-ink-muted",
  "bg-surface-1 text-ink",
  "bg-surface-1 text-ink-muted",
];

function initials(name: string): string {
  const words = name
    .replace(/[^A-Za-z\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !/^(the|and|for|of|in)$/i.test(w));
  return (words[0]?.[0] ?? "?").toUpperCase() + (words[1]?.[0] ?? "").toUpperCase();
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function ProviderLogo({
  domain,
  name,
  size = 40,
}: {
  domain?: string | null;
  name: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const canHotlink = Boolean(CLIENT_ID && domain && !failed);

  if (!canHotlink) {
    const tint = TINTS[hash(name) % TINTS.length];
    return (
      <span
        aria-hidden="true"
        style={{ width: size, height: size }}
        className={`fr-caption grid shrink-0 place-items-center rounded-md ${tint}`}
      >
        {initials(name)}
      </span>
    );
  }

  return (
    <img
      // Explicit /domain/ route: without a type prefix the CDN guesses between
      // domain, ticker, ISIN and crypto, and "mit.edu"-shaped inputs are not
      // worth leaving to a guess.
      src={`https://cdn.brandfetch.io/domain/${domain}/w/${size * 2}/h/${size * 2}?c=${CLIENT_ID}`}
      // Decorative: the provider name is already printed next to it, so an
      // alt text would just make screen readers say it twice.
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      style={{ width: size, height: size }}
      className="shrink-0 rounded-md bg-surface-2 object-contain p-1"
    />
  );
}
