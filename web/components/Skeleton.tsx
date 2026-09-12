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
    <div className="rounded-xl bg-surface-1 p-lg">
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
 * Placeholder for the profile form while a document is being parsed.
 *
 * Mirrors the real form's grid so the fields do not jump into place when the
 * extraction lands — a skeleton with the wrong shape trades a spinner for a
 * layout shift, which is the worse bug.
 */
export function FormSkeleton() {
  return (
    <div
      className="flex flex-col gap-lg"
      aria-busy="true"
      aria-live="polite"
      aria-label="Reading your document"
    >
      <div className="grid gap-lg sm:grid-cols-2">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="grid gap-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-11 w-full" />
          </div>
        ))}
      </div>
      <div className="grid gap-2">
        <Skeleton className="h-4 w-32" />
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-7 w-24" />
          ))}
        </div>
      </div>
      <Skeleton className="h-12 w-40" />
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
      className="flex flex-col gap-md"
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
