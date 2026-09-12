"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useId, useState } from "react";

import { fetchVisaReadiness, formatDate, hasPassport, type VisaCheck } from "@/lib/visa";

/**
 * Progressive disclosure of visa readiness for one scholarship's host country.
 *
 * Fetched lazily on first expand, not with the match stream: most students
 * open one or two cards, and the upstream is rate-limited. lib/visa.ts caches
 * per destination so several programmes in the same country share one request.
 *
 * Typography and spacing use the DESIGN.md tokens — fr-caption eyebrows,
 * fr-body-sm rows, and the 5px rhythm (gap-xs / mt-sm / mt-md).
 */

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-md first:mt-0">
      <p className="fr-caption uppercase text-ink-muted" style={{ letterSpacing: "0.1em" }}>
        {label}
      </p>
      <div className="mt-xs">{children}</div>
    </div>
  );
}

export function VisaReadiness({
  destination,
  scholarshipTitle,
}: {
  destination: string | null;
  scholarshipTitle: string;
}) {
  const reduced = useReducedMotion();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<VisaCheck | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  // null = not resolved yet. Resolved on mount so the first click is instant;
  // the promise is shared across every card on the page.
  const [passport, setPassport] = useState<boolean | null>(null);
  const [needsPassport, setNeedsPassport] = useState(false);

  useEffect(() => {
    let live = true;
    hasPassport().then((v) => live && setPassport(v));
    return () => {
      live = false;
    };
  }, []);

  const toggle = useCallback(async () => {
    if (open) {
      setOpen(false);
      return;
    }

    /*
      The gate. Visa requirements are a function of (passport, destination),
      and /v1/visa/check rejects the call outright when the session carries no
      passport — so opening the panel without one costs a round-trip and shows
      a generic failure that hides the one thing the student can act on.
      Await rather than read state: a click landing before the mount lookup
      resolves must still be gated, not let through.
    */
    const ok = passport ?? (await hasPassport());
    setPassport(ok);
    if (!ok) {
      setNeedsPassport(true);
      return;
    }

    setNeedsPassport(false);
    setOpen(true);
    if (!data && !loading && destination) {
      setLoading(true);
      setError(false);
      fetchVisaReadiness(destination)
        .then(setData)
        .catch(() => setError(true))
        .finally(() => setLoading(false));
    }
  }, [open, data, loading, destination, passport]);

  const readiness = data?.readiness;
  const verified = formatDate(readiness?.source_last_verified);
  const retrieved = formatDate(readiness?.retrieved_at);

  return (
    <div className="mt-md border-t border-hairline pt-md">
      {/*
        Inline rather than a toast: the missing value belongs to THIS control,
        and a corner notification detaches the explanation from the button the
        student just pressed. relative z-10 for the same reason as the button
        below — the card-wide ::after overlay would otherwise swallow the link.
      */}
      <AnimatePresence initial={false}>
        {needsPassport && (
          <motion.div
            key="needs-passport"
            role="status"
            aria-live="polite"
            initial={reduced ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="relative z-10 overflow-hidden"
          >
            <div className="mb-sm flex flex-wrap items-center gap-sm rounded-md border border-hairline bg-surface-2 p-sm">
              {/* ink-muted #999 on surface-2 #1c1c1c = 6.0:1. */}
              <p className="fr-body-sm min-w-0 flex-1 text-ink-muted">
                Please add your passport nationality in your application form to
                unlock destination-specific visa requirements.
              </p>
              <Link
                href="/start#passport-country"
                className="fr-btn-secondary shrink-0"
              >
                Add passport
              </Link>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/*
        relative z-10 is load-bearing. The card title's ::after overlay spans
        the whole card to make it one click target for the handoff; without
        lifting this button above it, every tap here would open the external
        application page instead of expanding the panel.
      */}
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={panelId}
        className="fr-btn-secondary relative z-10"
      >
        <span>
          {open ? "Hide visa readiness" : "Expand for Visa Readiness"}
          <span className="sr-only"> for {scholarshipTitle}</span>
        </span>
        <motion.span
          aria-hidden="true"
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="inline-block"
        >
          ▾
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={panelId}
            key="panel"
            initial={reduced ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-md">
              {!destination && (
                <p className="fr-body-sm text-ink-muted">
                  This programme does not state a single host country — joint
                  degrees span several. Check the visa route for whichever
                  country you would start in.
                </p>
              )}

              {destination && loading && (
                <div className="flex flex-col gap-xs" aria-busy="true">
                  <span className="sc-skeleton h-4 w-40" />
                  <span className="sc-skeleton h-4 w-full" />
                  <span className="sc-skeleton h-4 w-5/6" />
                </div>
              )}

              {destination && error && (
                <p className="fr-body-sm text-destructive">
                  Could not load visa information just now. Check with the
                  embassy before booking anything.
                </p>
              )}

              {destination && !loading && !error && data && (
                <>
                  <div className="flex flex-wrap items-center gap-xs">
                    <span className="fr-caption rounded-pill bg-surface-2 px-sm py-xxs text-ink">
                      {data.label}
                    </span>
                    <span className="fr-body-sm text-ink-muted">
                      {data.passport} → {data.destination}
                      {data.visa_free_days ? ` · ${data.visa_free_days} days visa-free` : ""}
                    </span>
                  </div>

                  {!data.available && (
                    <p className="fr-body-sm mt-sm text-ink-muted">
                      {data.message ??
                        "We could not verify this route. Check with the embassy."}
                    </p>
                  )}

                  {readiness && (
                    <>
                      {readiness.documents.length > 0 && (
                        <Section label="Documents required">
                          <ul className="flex flex-col gap-xxs">
                            {readiness.documents.map((d) => (
                              <li key={d} className="fr-body-sm text-ink">
                                — {d}
                              </li>
                            ))}
                          </ul>
                        </Section>
                      )}

                      {readiness.financial.length > 0 && (
                        <Section label="Financial proof">
                          <ul className="flex flex-col gap-xxs">
                            {readiness.financial.map((f) => (
                              <li key={f} className="fr-body-sm text-ink">
                                — {f}
                              </li>
                            ))}
                          </ul>
                          <p className="fr-micro mt-xxs text-ink-muted">
                            Drawn from the documents list above — the evidence of
                            means students most often miss.
                          </p>
                        </Section>
                      )}

                      {readiness.passport_validity_months != null && (
                        <Section label="Passport validity">
                          <p className="fr-body-sm text-ink">
                            {/*
                              0 is a real answer, not missing data — the UK asks
                              for no validity beyond the stay itself. Rendering
                              it literally ("valid for at least 0 months") reads
                              as a bug and tells the student nothing.
                            */}
                            {readiness.passport_validity_months > 0
                              ? `Valid for at least ${readiness.passport_validity_months} months beyond your stay.`
                              : "No validity required beyond the length of your stay."}
                          </p>
                        </Section>
                      )}

                      {readiness.process.length > 0 && (
                        <Section label="Application process">
                          <ol className="flex flex-col gap-xxs">
                            {readiness.process.map((step, i) => (
                              <li key={step} className="fr-body-sm text-ink">
                                {i + 1}. {step}
                              </li>
                            ))}
                          </ol>
                        </Section>
                      )}

                      {/*
                        Two different dates, never conflated: what the publisher
                        verified vs when we fetched it. Calling our fetch time a
                        verification date would overstate how fresh the rule is.
                      */}
                      <p className="fr-micro mt-md border-t border-hairline-soft pt-sm text-ink-muted">
                        {verified
                          ? `Source last verified ${verified}.`
                          : "The source did not publish a verification date."}
                        {retrieved ? ` Retrieved by ScholarCompass ${retrieved}.` : ""}
                        {readiness.sources[0]?.url && (
                          <>
                            {" "}
                            <a
                              href={readiness.sources[0].url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="fr-link relative z-10"
                            >
                              View source
                            </a>
                          </>
                        )}
                      </p>
                    </>
                  )}

                  {!readiness && data.available && (
                    <p className="fr-body-sm mt-sm text-ink-muted">
                      We hold the entry rule for this route but no document
                      checklist yet. Confirm requirements with the embassy.
                    </p>
                  )}
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
