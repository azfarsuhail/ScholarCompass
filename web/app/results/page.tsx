"use client";

import Link from "next/link";

import { MatchStream } from "@/components/MatchStream";
import { StepIndicator } from "@/components/StepIndicator";
import { retentionLabel } from "@/lib/retention";

export default function ResultsPage() {
  return (
    <main id="main" className="mx-auto w-full max-w-[760px] flex-1 px-lg py-xxl sm:px-xl">
      <StepIndicator current={1} />

      {/* autoStart: arriving here means the form was submitted, so making the
          student press another button would just add a step to the funnel. */}
      <MatchStream autoStart />

      <div className="mt-xxl flex flex-wrap items-center gap-md border-t border-hairline-soft pt-lg">
        <Link
          href="/start"
          className="fr-link fr-body-sm inline-flex min-h-11 items-center"
        >
          ← Change my answers
        </Link>
        <p className="fr-body-sm text-ink-muted">
          Nothing here is saved to an account. It expires on its own within {retentionLabel}.
        </p>
      </div>
    </main>
  );
}
