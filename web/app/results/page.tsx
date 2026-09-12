"use client";

import Link from "next/link";

import { MatchStream } from "@/components/MatchStream";
import { StepIndicator } from "@/components/StepIndicator";

export default function ResultsPage() {
  return (
    <main id="main" className="mx-auto w-full max-w-2xl flex-1 px-6 py-12">
      <StepIndicator current={1} />

      {/* autoStart: arriving here means the form was submitted, so making the
          student press another button would just add a step to the funnel. */}
      <MatchStream autoStart />

      <div className="mt-10 flex flex-wrap items-center gap-4 border-t border-border pt-6">
        <Link
          href="/start"
          className="min-h-11 cursor-pointer font-bold text-accent underline decoration-border underline-offset-4 transition-colors duration-200 hover:decoration-current"
        >
          ← Change my answers
        </Link>
        <p className="text-sm text-muted-foreground">
          Nothing here is saved to an account. It expires on its own within 72
          hours.
        </p>
      </div>
    </main>
  );
}
