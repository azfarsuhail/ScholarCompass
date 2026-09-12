"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { ProviderLogo } from "@/components/ProviderLogo";
import { VerifiedBadge } from "@/components/VerifiedBadge";
import { useFavorites, type SavedScholarship } from "@/lib/favorites";

/**
 * Side-by-side comparison of saved scholarships.
 *
 * A real <table> rather than a grid of divs: this is tabular data, and the
 * table gives row/column header semantics to a screen reader for free — which
 * is the entire point of a comparison view. The left header column is sticky
 * so a student scrolling to the fourth award still knows which row is
 * "Deadline", matching DESIGN.md's documented comparison-table behaviour
 * ("fixed-width left column with horizontally scrolling tier columns").
 */

function formatDeadline(s: SavedScholarship): string {
  if (s.is_rolling) return "Rolling";
  if (!s.deadline) return s.deadline_note ? "Announced annually" : "Not stated";
  return new Date(s.deadline).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const ROWS: { label: string; render: (s: SavedScholarship) => React.ReactNode }[] = [
  { label: "Provider", render: (s) => s.provider ?? "—" },
  { label: "Country", render: (s) => s.host_country_iso3 ?? "—" },
  {
    label: "Funding",
    render: (s) => (s.funding_type ? s.funding_type : "Not stated"),
  },
  { label: "Deadline", render: formatDeadline },
  {
    label: "Min GPA",
    // "—" is genuinely different from 0.0 and must not read as a requirement.
    render: (s) => (s.min_gpa_4 == null ? "Not stated" : s.min_gpa_4.toFixed(2)),
  },
  {
    label: "Fields",
    render: (s) =>
      s.fields_of_study.length ? s.fields_of_study.join(", ") : "Not tagged",
  },
  { label: "Verified", render: (s) => <VerifiedBadge at={s.last_verified_at} /> },
];

export function ComparePanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { items, remove, clear } = useFavorites();
  const reduced = useReducedMotion();
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Escape to close, and the page behind must not scroll while a modal layer
  // is over it.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    // Move focus into the dialog, or a keyboard user is left behind on the
    // trigger with the panel unreachable.
    closeRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60"
            aria-hidden="true"
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            initial={reduced ? false : { x: "100%" }}
            animate={{ x: 0 }}
            exit={reduced ? { opacity: 0 } : { x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 36, mass: 0.9 }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-3xl flex-col border-l border-hairline bg-canvas"
          >
            <header className="flex items-start justify-between gap-md border-b border-hairline p-lg">
              <div>
                <h2 id={titleId} className="fr-headline text-ink">
                  Saved scholarships
                </h2>
                <p className="fr-body-sm mt-xxs text-ink-muted">
                  {items.length === 0
                    ? "Nothing saved yet."
                    : `${items.length} saved · kept in this browser only, never sent to us`}
                </p>
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label="Close saved scholarships"
                className="grid size-11 shrink-0 cursor-pointer place-items-center rounded-full text-ink-muted transition-colors hover:bg-surface-1 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue"
              >
                <X aria-hidden="true" className="size-5" />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-auto p-lg">
              {items.length === 0 ? (
                <p className="fr-body text-ink-muted">
                  Use “Save” on any result to line it up here against the others.
                </p>
              ) : (
                <table className="w-full border-collapse text-left">
                  <caption className="sr-only">
                    Saved scholarships compared across provider, country, funding,
                    deadline, minimum GPA, fields and verification date
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="sticky left-0 z-10 bg-canvas">
                        <span className="sr-only">Attribute</span>
                      </th>
                      {items.map((s) => (
                        <th
                          key={s.id}
                          scope="col"
                          className="min-w-[220px] border-b border-hairline p-sm align-top"
                        >
                          <span className="flex items-start gap-xs">
                            <ProviderLogo
                              domain={s.provider_domain}
                              name={s.provider ?? s.title}
                              size={28}
                            />
                            <span className="min-w-0 flex-1">
                              <a
                                href={s.source_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="fr-body-sm text-ink hover:text-accent-blue"
                              >
                                {s.title}
                              </a>
                            </span>
                          </span>
                          <button
                            type="button"
                            onClick={() => remove(s.id)}
                            className="fr-micro mt-xs cursor-pointer text-ink-muted underline-offset-2 hover:text-ink hover:underline"
                          >
                            Remove
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ROWS.map((row) => (
                      <tr key={row.label}>
                        <th
                          scope="row"
                          className="fr-caption sticky left-0 z-10 w-[110px] border-b border-hairline-soft bg-canvas py-sm pr-md align-top font-medium text-ink-muted"
                        >
                          {row.label}
                        </th>
                        {items.map((s) => (
                          <td
                            key={s.id}
                            className="fr-body-sm border-b border-hairline-soft p-sm align-top text-ink"
                          >
                            {row.render(s)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr>
                      <th scope="row" className="sticky left-0 z-10 bg-canvas">
                        <span className="sr-only">Apply</span>
                      </th>
                      {items.map((s) => (
                        <td key={s.id} className="p-sm align-top">
                          <a
                            href={s.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="fr-body-sm text-accent-blue"
                          >
                            Apply ↗
                            <span className="sr-only">
                              {` — ${s.title} (opens the official application page in a new tab)`}
                            </span>
                          </a>
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              )}
            </div>

            {items.length > 0 && (
              <footer className="border-t border-hairline p-lg">
                <button type="button" onClick={clear} className="fr-btn-secondary">
                  Clear all
                </button>
              </footer>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
