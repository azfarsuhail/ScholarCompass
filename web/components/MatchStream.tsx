"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ComparePanel } from "@/components/ComparePanel";
import { MatchCard } from "@/components/MatchCard";
import { MatchListSkeleton } from "@/components/Skeleton";
import { API_BASE } from "@/lib/api";
import { useFavorites } from "@/lib/favorites";
import type { Enrichment, MatchEvent, RunEvent } from "@/lib/types";

type Status = "idle" | "streaming" | "done" | "error";

export function MatchStream({ autoStart = false }: { autoStart?: boolean }) {
  const [run, setRun] = useState<RunEvent | null>(null);
  const [matches, setMatches] = useState<MatchEvent[]>([]);
  const [enrichments, setEnrichments] = useState<Record<number, Enrichment>>({});
  const [status, setStatus] = useState<Status>("idle");
  const [compareOpen, setCompareOpen] = useState(false);
  const { count: savedCount } = useFavorites();
  const sourceRef = useRef<EventSource | null>(null);

  const start = useCallback(() => {
    sourceRef.current?.close();
    setRun(null);
    setMatches([]);
    setEnrichments({});
    setStatus("streaming");

    // EventSource sends the HttpOnly session cookie automatically because the
    // request is same-origin (next.config.ts rewrites /api/* to the backend).
    const es = new EventSource(`${API_BASE}/v1/match/stream`);
    sourceRef.current = es;

    es.addEventListener("run", (e) => setRun(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("match", (e) =>
      setMatches((prev) => [...prev, JSON.parse((e as MessageEvent).data)]),
    );
    es.addEventListener("enrichment", (e) => {
      const data: Enrichment = JSON.parse((e as MessageEvent).data);
      setEnrichments((prev) => ({ ...prev, [data.index]: data }));
    });
    es.addEventListener("done", () => {
      setStatus("done");
      es.close();
    });
    es.onerror = () => {
      // EventSource auto-reconnects on error, which would silently restart the
      // whole run. Close it and let the student retry deliberately.
      es.close();
      setStatus((s) => (s === "done" ? s : "error"));
    };
  }, []);

  useEffect(() => {
    if (autoStart) start();
    return () => sourceRef.current?.close();
  }, [autoStart, start]);

  const exact = matches.filter((m) => m.is_exact).length;
  const widened = run && run.relaxation_level !== "R0";
  const scoredCount = Object.keys(enrichments).length;

  /**
   * Rank by AI fit score, descending, as the Groq stream resolves.
   *
   * Two rules keep this from thrashing while enrichments trickle in:
   *  - Unscored cards hold their deterministic order relative to each other
   *    (by `index`), so the list is stable before any score arrives.
   *  - Unscored cards sink below scored ones rather than being treated as 0,
   *    which would shove a not-yet-rated exact match to the bottom and then
   *    yank it back a second later.
   *
   * NOTE: this ranks a high-scoring "stretch" above a lower-scoring exact
   * match. The eligibility badge stays on every card so the distinction is
   * never hidden, but it IS a change from ranking eligibility-first.
   */
  const ranked = [...matches].sort((a, b) => {
    const sa = enrichments[a.index]?.score;
    const sb = enrichments[b.index]?.score;
    if (sa == null && sb == null) return a.index - b.index;
    if (sa == null) return 1;
    if (sb == null) return -1;
    if (sb !== sa) return sb - sa;
    return a.index - b.index;
  });

  return (
    <section aria-labelledby="results-heading">
      <div className="flex flex-wrap items-end justify-between gap-md">
        <div>
          <h1 id="results-heading" className="fr-display-lg text-ink">
            Your matches
          </h1>
          {run && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="fr-body-sm mt-xs text-ink-muted"
            >
              {matches.length} {matches.length === 1 ? "result" : "results"}
              {exact > 0 && ` · ${exact} exact`} · checked in {run.deterministic_ms}ms
              {scoredCount > 0 && ` · ranked by AI fit (${scoredCount} scored)`}
            </motion.p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-sm">
          {savedCount > 0 && (
            <button
              type="button"
              onClick={() => setCompareOpen(true)}
              className="fr-btn-secondary"
            >
              Compare
              {/* Surface lift for the count, not a chromatic fill — sky blue
                  stays reserved for links, focus and selection. */}
              <span className="fr-caption rounded-pill bg-surface-2 px-xs py-xxs text-ink">
                {savedCount}
              </span>
            </button>
          )}
          <button type="button" onClick={start} className="fr-btn-secondary">
            Search again
          </button>
        </div>
      </div>

      {/* Announced once, politely — not one announcement per arriving card. */}
      <p className="sr-only" role="status" aria-live="polite">
        {status === "streaming"
          ? "Searching for scholarships"
          : status === "done"
            ? `${matches.length} matches found`
            : ""}
      </p>

      {widened && (
        <motion.p
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="fr-body-sm mt-md rounded-md bg-surface-1 p-md text-ink-muted"
        >
          There were few exact matches, so we widened the search. Everything
          below is labelled with what it would take.
        </motion.p>
      )}

      {status === "error" && (
        <p
          role="alert"
          className="fr-body-sm mt-md rounded-md border border-destructive p-md text-destructive"
        >
          {/*
            EventSource exposes no status code to onerror, so a 429 from the
            rate limiter and a dropped connection are indistinguishable here.
            Rather than guess, the copy covers both and the remedy is the same.
          */}
          The search stopped. That is usually a dropped connection, or too many
          searches in a short window — wait a moment, then press “Search again”.
          Your answers are still saved.
        </p>
      )}

      {/* Skeletons only before the first card. Once deterministic results are
          on screen, enrichments fill in beneath them rather than replacing the
          page with a loading state. */}
      {status === "streaming" && matches.length === 0 && (
        <div className="mt-lg">
          <MatchListSkeleton count={4} />
        </div>
      )}

      <motion.ul layout className="mt-lg flex flex-col gap-md">
        <AnimatePresence initial={false}>
          {ranked.map((m) => (
            <MatchCard
              key={m.scholarship.id}
              match={m}
              enrichment={enrichments[m.index]}
            />
          ))}
        </AnimatePresence>
      </motion.ul>

      <ComparePanel open={compareOpen} onClose={() => setCompareOpen(false)} />

      {status === "done" && matches.length === 0 && (
        <p className="fr-body mt-lg rounded-xl bg-surface-1 p-lg text-ink-muted">
          Nothing matched, even after widening the search. Rather than show you
          opportunities you cannot apply for, we would rather say so — try a
          different degree level or field.
        </p>
      )}
    </section>
  );
}
