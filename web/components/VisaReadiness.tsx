"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useId, useState } from "react";

import { fetchVisaReadiness, formatDate, type VisaCheck } from "@/lib/visa";

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

  const toggle = useCallback(() => {
    const next = !open;
    setOpen(next);
    if (next && !data && !loading && destination) {
      setLoading(true);
      setError(false);
      fetchVisaReadiness(destination)
        .then(setData)
        .catch(() => setError(true))
        .finally(() => setLoading(false));
    }
  }, [open, data, loading, destination]);

  const readiness = data?.readiness;
  const verified = formatDate(readiness?.source_last_verified);
  const retrieved = formatDate(readiness?.retrieved_at);

  return (
    <div className="mt-md border-t border-hairline pt-md">
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
