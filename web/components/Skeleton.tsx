/**
 * Skeleton loaders.
 *
 * Server component on purpose — skeletons ship no interactivity, so there is
 * no reason to send them through the client bundle. The shimmer is pure CSS
 * (.sc-skeleton in globals.css) and is disabled under prefers-reduced-motion.
 *
 * Every skeleton reserves the same box as the real content it stands in for.
 * That is the whole point: a skeleton that is the wrong height trades a
 * spinner for a layout shift, which is a worse bug than the one it fixed.
 */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`sc-skeleton ${className}`} aria-hidden="true" />;
}

/** Placeholder for one streaming match card. Matches MatchCard's box exactly. */
export function MatchCardSkeleton() {
  return (
    <div className="rounded-sc border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-6 w-16 shrink-0" />
      </div>
      <Skeleton className="mt-3 h-4 w-1/3" />
      <Skeleton className="mt-4 h-4 w-full" />
      <Skeleton className="mt-2 h-4 w-5/6" />
    </div>
  );
}

/**
 * The list-level loading state.
 *
 * `aria-busy` + a polite live region means a screen reader announces "Finding
 * scholarships" once, instead of narrating every skeleton box as it appears.
 */
export function MatchListSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div
      className="flex flex-col gap-3"
      aria-busy="true"
      aria-live="polite"
      aria-label="Finding scholarships"
    >
      {Array.from({ length: count }, (_, i) => (
        <MatchCardSkeleton key={i} />
      ))}
    </div>
  );
}
