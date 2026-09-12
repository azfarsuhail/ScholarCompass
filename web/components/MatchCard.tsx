"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import { LEVEL_LABEL, type Enrichment, type MatchEvent } from "@/lib/types";

const TONE_CLASS: Record<string, string> = {
  exact: "border-exact text-exact",
  near: "border-near text-near",
  stretch: "border-stretch text-stretch",
};

function formatDeadline(m: MatchEvent): string {
  if (m.scholarship.is_rolling) return "Rolling — no fixed deadline";
  if (!m.scholarship.deadline) return "Deadline not stated";
  return new Date(m.scholarship.deadline).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function MatchCard({
  match,
  enrichment,
}: {
  match: MatchEvent;
  enrichment?: Enrichment;
}) {
  const reduced = useReducedMotion();
  const { label, tone } = LEVEL_LABEL[match.level];
  const s = match.scholarship;

  return (
    <motion.li
      layout={!reduced}
      initial={reduced ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      className="rounded-sc border border-border bg-card p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-bold text-card-foreground">
          <a
            href={s.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="cursor-pointer underline decoration-border underline-offset-4 transition-colors duration-200 hover:decoration-current"
          >
            {s.title}
          </a>
        </h3>
        {/* Text carries the meaning; the colour only reinforces it. */}
        <span
          className={`shrink-0 rounded-sc border px-2 py-1 text-xs font-bold ${TONE_CLASS[tone]}`}
        >
          {label}
        </span>
      </div>

      <p className="mt-1 text-sm text-muted-foreground">
        {[s.provider, s.host_country_iso3].filter(Boolean).join(" · ")}
        {" · "}
        {formatDeadline(match)}
      </p>

      {match.notes.map((n) => (
        <p key={n} className="mt-2 text-sm text-warning">
          {n}
        </p>
      ))}

      {match.gaps.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1">
          {match.gaps.map((g) => (
            <li key={g} className="text-sm text-muted-foreground">
              — {g}
            </li>
          ))}
        </ul>
      )}

      {/*
        The AI layer. It animates in behind the deterministic card and is
        always visibly attributed, so a student can tell which parts of the
        page are database facts and which are a model's opinion.
      */}
      <AnimatePresence>
        {enrichment && (
          <motion.div
            initial={reduced ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-3 border-t border-border pt-3">
              <p className="text-sm text-card-foreground">{enrichment.rationale}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                AI-assessed fit: {Math.round(enrichment.score)}/100 · not an
                eligibility decision
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}
