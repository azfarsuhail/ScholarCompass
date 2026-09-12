"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import { ProviderLogo } from "@/components/ProviderLogo";
import { LEVEL_LABEL, type Enrichment, type MatchEvent } from "@/lib/types";

const TONE_CLASS: Record<string, string> = {
  exact: "border-exact text-exact",
  near: "border-near text-near",
  stretch: "border-stretch text-stretch",
};

function formatDeadline(m: MatchEvent): string {
  if (m.scholarship.is_rolling) return "Rolling — no fixed deadline";
  if (!m.scholarship.deadline) {
    // DAAD publishes a policy rather than a date; the crawler records that
    // distinction so this does not read as a blank we failed to fill.
    return m.scholarship.deadline_note
      ? "Deadline announced annually"
      : "Deadline not stated";
  }
  return new Date(m.scholarship.deadline).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "official site";
  }
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
      whileHover={reduced ? undefined : { y: -2 }}
      className="group relative rounded-sc border border-border bg-card p-4 transition-colors duration-200 focus-within:border-accent hover:border-accent"
    >
      <div className="flex items-start gap-3">
        <ProviderLogo
          domain={s.provider_domain}
          name={s.provider ?? s.title}
          size={40}
        />
        <h3 className="min-w-0 flex-1 font-bold text-card-foreground">
          {/*
            The handoff. The whole card is the click target via ::after, so
            there is one unambiguous action per result and no intermediate
            detail page between the student and the real application form.
            New tab, not same-tab: a demo (or a student) that loses its results
            on every outbound click is worse, and rel=noopener is required
            anyway for an untrusted external origin.
          */}
          <a
            href={s.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="cursor-pointer underline decoration-border underline-offset-4 transition-colors duration-200 after:absolute after:inset-0 after:content-[''] group-hover:decoration-current"
          >
            {s.title}
          </a>
        </h3>
        {/* Text carries the meaning; colour only reinforces it. */}
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
        AI layer: animates in behind the deterministic card and is always
        attributed, so a student can tell which parts are database facts and
        which are a model's opinion.
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

      <p className="mt-4 text-sm font-bold text-accent">
        Apply on {hostname(s.source_url)}{" "}
        <span aria-hidden="true" className="inline-block transition-transform duration-200 group-hover:translate-x-0.5">
          ↗
        </span>
        <span className="sr-only"> (opens the official application page in a new tab)</span>
      </p>
    </motion.li>
  );
}
