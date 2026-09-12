"use client";

import { motion, useReducedMotion } from "motion/react";

export const STEPS = ["Your details", "Your matches", "Apply"] as const;

/**
 * Progress through the funnel.
 *
 * A step indicator is only honest if it also reads correctly without colour:
 * the current step is marked with aria-current, completed steps are announced
 * as completed, and the numeral is always visible. Colour is reinforcement.
 */
export function StepIndicator({ current }: { current: 0 | 1 | 2 }) {
  const reduced = useReducedMotion();

  return (
    <nav aria-label="Progress" className="mb-xl">
      <ol className="flex items-center gap-2 sm:gap-3">
        {STEPS.map((label, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={label} className="flex flex-1 items-center gap-2 sm:gap-3">
              <div className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  // pricing-tab semantics: selected = surface LIFT, not a
                  // chromatic fill. DESIGN.md keeps blue for signal only.
                  className={[
                    "grid size-8 shrink-0 place-items-center rounded-full text-xs font-medium transition-colors duration-200",
                    done
                      ? "bg-primary text-primary-foreground"
                      : active
                        ? "bg-surface-2 text-ink"
                        : "bg-surface-1 text-ink-muted",
                  ].join(" ")}
                >
                  {done ? "✓" : i + 1}
                </span>
                <span
                  aria-current={active ? "step" : undefined}
                  className={[
                    "whitespace-nowrap text-sm",
                    // Three nowrap labels plus connectors overflow a 360px
                    // screen. Below sm only the CURRENT step is named — the
                    // numbered circles still carry the sequence, and the
                    // screen-reader text below is unconditional, so nothing is
                    // lost for assistive tech.
                    active ? "fr-body-sm text-ink" : "fr-body-sm hidden text-ink-muted sm:inline",
                  ].join(" ")}
                >
                  <span className="sr-only">
                    {done ? "Completed: " : active ? "Current step: " : "Upcoming: "}
                  </span>
                  {label}
                </span>
              </div>

              {i < STEPS.length - 1 && (
                <div className="relative h-px flex-1 bg-hairline" aria-hidden="true">
                  <motion.div
                    className="absolute inset-y-0 left-0 bg-primary"
                    initial={reduced ? false : { width: 0 }}
                    animate={{ width: done ? "100%" : "0%" }}
                    transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
