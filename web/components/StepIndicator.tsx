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
    <nav aria-label="Progress" className="mb-10">
      <ol className="flex items-center gap-2 sm:gap-3">
        {STEPS.map((label, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={label} className="flex flex-1 items-center gap-2 sm:gap-3">
              <div className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={[
                    "grid size-7 shrink-0 place-items-center rounded-full border text-xs font-bold transition-colors duration-300",
                    done
                      ? "border-accent bg-accent text-on-accent"
                      : active
                        ? "border-accent text-accent"
                        : "border-border text-muted-foreground",
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
                    active ? "font-bold text-foreground" : "hidden text-muted-foreground sm:inline",
                  ].join(" ")}
                >
                  <span className="sr-only">
                    {done ? "Completed: " : active ? "Current step: " : "Upcoming: "}
                  </span>
                  {label}
                </span>
              </div>

              {i < STEPS.length - 1 && (
                <div className="relative h-px flex-1 bg-border" aria-hidden="true">
                  <motion.div
                    className="absolute inset-y-0 left-0 bg-accent"
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
