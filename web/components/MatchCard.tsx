"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import { ProviderLogo } from "@/components/ProviderLogo";
import { VisaReadiness } from "@/components/VisaReadiness";
import { LEVEL_LABEL, type Enrichment, type MatchEvent } from "@/lib/types";

/**
 * Match card — DESIGN.md {components.product-mockup-tile}: surface-1 ground,
 * rounded-xl, level-2 elevation (light top edge + drop shadow).
 *
 * Hierarchy on this dark canvas is carried by ink → ink-muted, never by
 * opacity on white type. The level badge therefore uses SURFACE LIFT to mark
 * an exact match rather than a chromatic fill — DESIGN.md reserves blue for
 * links, focus and selection, and forbids a second accent family. The label
 * text still carries the meaning, so nothing is encoded by colour alone.
 */

const TONE_CLASS: Record<string, string> = {
  // surface-2 = lift = "exact". Muted charcoal = a stretch.
  exact: "bg-surface-2 text-ink",
  near: "bg-surface-1 text-ink-muted",
  stretch: "bg-surface-1 text-ink-muted",
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
      // `layout` does double duty here: it animates the card's own height when
      // the visa panel expands, AND glides the card to its new position when
      // the list is re-sorted by AI score. Without it, a card that jumps rank
      // mid-stream simply teleports.
      layout={!reduced}
      initial={reduced ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        // A spring on layout reads as movement; the opacity fade stays linear
        // so arriving cards do not feel bouncy.
        layout: { type: "spring", stiffness: 320, damping: 34, mass: 0.9 },
        duration: 0.32,
        ease: [0.22, 1, 0.36, 1],
      }}
      whileHover={reduced ? undefined : { y: -2 }}
      className="group fr-elev-2 relative rounded-xl bg-surface-1 p-lg transition-colors duration-200 hover:bg-surface-2 focus-within:bg-surface-2"
    >
      <div className="flex items-start gap-sm">
        <ProviderLogo domain={s.provider_domain} name={s.provider ?? s.title} size={40} />

        <h3 className="fr-headline min-w-0 flex-1 text-ink">
          {/*
            The handoff. The whole card is the click target via ::after, so
            there is one unambiguous action per result and no intermediate
            detail page between the student and the real application form.
            New tab: a student who loses their results on every outbound click
            is worse off, and rel=noopener is required for an external origin.
          */}
          <a
            href={s.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="cursor-pointer after:absolute after:inset-0 after:content-['']"
          >
            {s.title}
          </a>
        </h3>

        {/* Surface lift, not colour fill. Text carries the meaning. */}
        <span
          className={`fr-caption shrink-0 rounded-pill px-sm py-xxs ${TONE_CLASS[tone]}`}
        >
          {label}
        </span>
      </div>

      <p className="fr-body-sm mt-sm text-ink-muted">
        {[s.provider, s.host_country_iso3].filter(Boolean).join(" · ")}
        {" · "}
        {formatDeadline(match)}
      </p>

      {match.notes.map((n) => (
        <p key={n} className="fr-body-sm mt-sm text-ink">
          {n}
        </p>
      ))}

      {match.gaps.length > 0 && (
        <ul className="mt-sm flex flex-col gap-xxs">
          {match.gaps.map((g) => (
            <li key={g} className="fr-body-sm text-ink-muted">
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
            <div className="mt-md border-t border-hairline pt-md">
              <p className="fr-body text-ink">{enrichment.rationale}</p>
              <p className="fr-micro mt-xs text-ink-muted">
                AI-assessed fit: {Math.round(enrichment.score)}/100 · not an
                eligibility decision
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <VisaReadiness
        destination={s.host_country_iso3}
        scholarshipTitle={s.title}
      />

      {/* accent-blue: hyperlink. The one sanctioned use of the signal colour. */}
      <p className="fr-body-sm mt-md text-accent-blue">
        Apply on {hostname(s.source_url)}{" "}
        <span
          aria-hidden="true"
          className="inline-block transition-transform duration-200 group-hover:translate-x-0.5"
        >
          ↗
        </span>
        <span className="sr-only"> (opens the official application page in a new tab)</span>
      </p>
    </motion.li>
  );
}
