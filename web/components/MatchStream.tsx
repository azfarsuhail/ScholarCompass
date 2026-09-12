"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { MatchListSkeleton } from "@/components/Skeleton";
import { MatchCard } from "@/components/MatchCard";
import { API_BASE } from "@/lib/api";
import type { Enrichment, MatchEvent, RunEvent } from "@/lib/types";

type Status = "idle" | "streaming" | "done" | "error";

export function MatchStream({ ready }: { ready: boolean }) {
  const [run, setRun] = useState<RunEvent | null>(null);
  const [matches, setMatches] = useState<MatchEvent[]>([]);
  const [enrichments, setEnrichments] = useState<Record<number, Enrichment>>({});
  const [status, setStatus] = useState<Status>("idle");
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
      // EventSource auto-reconnects on error, which would restart the whole
      // run. Close it and let the student retry deliberately instead.
      es.close();
      setStatus((s) => (s === "done" ? s : "error"));
    };
  }, []);

  useEffect(() => () => sourceRef.current?.close(), []);

  if (!ready) return null;

  const exact = matches.filter((m) => m.is_exact).length;
  const widened = run && run.relaxation_level !== "R0";

  return (
    <section className="mt-8" aria-labelledby="results-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="results-heading" className="text-xl font-bold">
          Your matches
        </h2>
        <button
          type="button"
          onClick={start}
          className="min-h-11 cursor-pointer rounded-sc bg-accent px-5 font-bold text-on-accent transition-colors duration-200 hover:bg-primary hover:text-on-primary"
        >
          {status === "idle" ? "Find matches" : "Search again"}
        </button>
      </div>

      {/* Politely announced once, rather than narrating every arriving card. */}
      <p className="sr-only" role="status" aria-live="polite">
        {status === "streaming"
          ? "Searching for scholarships"
          : status === "done"
            ? `${matches.length} matches found`
            : ""}
      </p>

      {run && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-3 text-sm text-muted-foreground"
        >
          {matches.length} {matches.length === 1 ? "result" : "results"}
          {exact > 0 && ` · ${exact} exact`} · found in {run.deterministic_ms}ms
          {widened &&
            " · we widened the search because there were few exact matches"}
        </motion.p>
      )}

      {status === "error" && (
        <p className="mt-4 rounded-sc border border-destructive p-3 text-sm text-destructive">
          The search stopped unexpectedly. Your answers are still here — press
          “Search again”.
        </p>
      )}

      {/* Skeletons only before the first card. Once deterministic results are
          on screen, enrichments fill in beneath them rather than replacing
          the page with a loading state. */}
      {status === "streaming" && matches.length === 0 && (
        <div className="mt-4">
          <MatchListSkeleton count={4} />
        </div>
      )}

      <motion.ul layout className="mt-4 flex flex-col gap-3">
        <AnimatePresence initial={false}>
          {matches.map((m) => (
            <MatchCard
              key={m.scholarship.id}
              match={m}
              enrichment={enrichments[m.index]}
            />
          ))}
        </AnimatePresence>
      </motion.ul>

      {status === "done" && matches.length === 0 && (
        <p className="mt-4 rounded-sc border border-border bg-card p-4 text-muted-foreground">
          Nothing matched, even after widening the search. Rather than show you
          opportunities you cannot apply for, we would rather say so — try a
          different degree level or field.
        </p>
      )}
    </section>
  );
}
