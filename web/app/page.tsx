// Server component. `motion/react-client` animates without pulling this page
// into the client bundle — the LCP element stays server-rendered HTML.
import * as motion from "motion/react-client";
import Image from "next/image";
import Link from "next/link";

import { HeroReveal } from "@/components/HeroReveal";
import { Reveal } from "@/components/Reveal";
import { retentionLabel } from "@/lib/retention";

const PROOF = [
  {
    figure: "261",
    label: "programmes crawled live",
    sub: "Erasmus Mundus · DAAD · Commonwealth · Chevening · Eiffel",
  },
  { figure: "<5s", label: "to first results", sub: "before any AI runs" },
  { figure: "0", label: "accounts, ever", sub: `nothing kept after ${retentionLabel}` },
];

const STEPS = [
  {
    n: "01",
    title: "Tell us the basics",
    body: "Six fields, all optional. Or upload a CV and we read your degree, grades, skills and roles straight off it — including marking schemes a naive percentage conversion gets wrong.",
  },
  {
    n: "02",
    title: "See what you qualify for",
    body: "Hard rules — nationality, degree level, GPA, deadlines, work hours — are checked against the database first. Exact matches are labelled exact. Stretches say precisely what is missing.",
  },
  {
    n: "03",
    title: "Go straight to the application",
    body: "Every result links to the official programme page. No intermediate landing page, no affiliate hop, no account wall.",
  },
];

export default function Home() {
  return (
    <main id="main" className="flex-1">
      {/* Hero — canvas band. On this system the dark canvas IS the whitespace.
          The geometry layer now lives in the root layout, fixed to the
          viewport, so it persists across routes rather than remounting here. */}
      <section className="relative mx-auto w-full max-w-[1199px] px-lg py-section sm:px-xl">
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4 }}
          className="fr-caption uppercase text-ink-muted"
          style={{ letterSpacing: "0.12em" }}
        >
          ScholarCompass
        </motion.p>

        <h1 className="fr-display-xxl mt-md max-w-[14ch] text-ink">
          <HeroReveal>Scholarships you can actually get.</HeroReveal>
        </h1>

        {/*
          Side-by-side band: lead copy + CTA on one side, the product mockup
          directly beside it on desktop. Stacks to one column below lg.
          gap-xl (30px) and mt-xl keep the 5px spacing rhythm.
          items-center so the copy is optically centred against the taller
          image rather than pinned to its top edge.
        */}
        <div className="mt-xl grid grid-cols-1 items-center gap-xl lg:grid-cols-2">
          <div>
            <motion.p
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
              className="fr-body-lg max-w-[52ch] text-ink-muted"
            >
              Most search tools show you everything, then let you discover you
              were ineligible after the application fee. We check the rules
              first, then send you straight to the official page.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
              className="mt-xl flex flex-wrap items-center gap-md"
            >
              {/* button-primary: the only primary CTA shape in the system. */}
              <Link href="/start" className="fr-btn-primary">
                Find my scholarships
              </Link>
              <span className="fr-body-sm text-ink-muted">
                No sign-up. About two minutes.
              </span>
            </motion.div>
          </div>

          {/*
            product-mockup-tile: DESIGN.md > Shapes > "Embedded site mockups sit
            in {rounded.xl} 20px tiles with {spacing.md} 15px interior padding",
            on a surface-1 ground with the level-2 light-edge treatment.
          */}
          <Reveal immediate delay={0.35} className="block">
            <div className="fr-elev-2 overflow-hidden rounded-xl bg-surface-1 p-md">
              <Image
                src="/images/hero-credentials.webp"
                // Decorative: the headline and subhead already carry the
                // meaning, so announcing this illustration would repeat them.
                alt=""
                aria-hidden="true"
                width={1600}
                height={893}
                // Still the LCP element. priority preloads it and skips the
                // lazy-loading intersection wait; 66KB keeps that cheap.
                priority
                fetchPriority="high"
                // Half-width at lg now, so the browser fetches a materially
                // smaller candidate than the old full-bleed 1139px.
                sizes="(max-width: 1023px) 100vw, 554px"
                className="h-auto w-full rounded-md"
              />
            </div>
          </Reveal>
        </div>

        <Reveal immediate delay={0.5} stagger="[data-proof]" className="mt-xxl block">
          <dl className="grid grid-cols-1 gap-lg sm:grid-cols-3">
            {PROOF.map((p) => (
              <div key={p.label} data-proof>
                <dt className="fr-display-md text-ink">{p.figure}</dt>
                <dd className="fr-body-sm mt-xxs text-ink-muted">
                  {p.label}
                  <span className="fr-micro mt-hair block">{p.sub}</span>
                </dd>
              </div>
            ))}
          </dl>
        </Reveal>
      </section>

      {/*
        Spotlight band. Gradients are the brand's atmosphere device and are
        scarce by design — "One or two per long page is the spec; three is a
        moodboard." Exactly two here, and they are CARDS inside a grid, never a
        section ground.
      */}
      <section className="mx-auto w-full max-w-[1199px] px-lg pb-section sm:px-xl">
        <Reveal stagger="[data-spot]">
          <div className="grid grid-cols-1 gap-lg md:grid-cols-2">
            <div data-spot className="fr-spotlight fr-spotlight-violet">
              <p className="fr-display-md">Eligibility is a database question.</p>
              <p className="fr-subhead mt-md text-ink">
                Nationality, degree level, GPA and deadlines are checked
                deterministically, before any model is asked for an opinion.
              </p>
            </div>
            <div data-spot className="fr-spotlight fr-spotlight-magenta">
              <p className="fr-display-md">Fit is a judgement call.</p>
              <p className="fr-subhead mt-md text-ink">
                Only that second question gets an AI. Its answer arrives behind
                your results and is always labelled as an opinion.
              </p>
            </div>
          </div>
        </Reveal>
      </section>

      {/* How it works — charcoal card band. Surface lift marks hierarchy. */}
      <section className="mx-auto w-full max-w-[1199px] px-lg pb-section sm:px-xl">
        <h2 className="fr-display-lg text-ink">How it works</h2>

        <Reveal stagger="[data-step]">
          <ol className="mt-xl grid grid-cols-1 gap-lg md:grid-cols-3">
            {STEPS.map((s) => (
              <li key={s.n} data-step className="fr-card fr-elev-2">
                <span className="fr-caption tabular-nums text-accent-blue">{s.n}</span>
                <h3 className="fr-headline mt-xs text-ink">{s.title}</h3>
                <p className="fr-body mt-sm text-ink-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </Reveal>

        <Reveal className="mt-xl block">
          <div className="fr-card fr-card-featured">
            <h2 className="fr-headline text-ink">Why there is no account</h2>
            <p className="fr-body mt-sm max-w-[70ch] text-ink-muted">
              Your CV is read in memory and discarded — we keep the extracted
              grade, never the file. Everything else expires within{" "}
              {retentionLabel} on its own, and you can erase it instantly at any
              point. There is no password to leak because there is no account to
              breach.
            </p>
            <Link href="/start" className="fr-btn-primary mt-lg">
              Start now
            </Link>
          </div>
        </Reveal>
      </section>

      {/* footer: canvas ground, ink-muted text, caption type. */}
      <footer className="border-t border-hairline-soft">
        <p className="fr-caption mx-auto w-full max-w-[1199px] px-lg py-xxl text-ink-muted sm:px-xl">
          ScholarCompass gives you sourced information, not immigration advice.
          Confirm with the official embassy or university before you pay
          anything or book travel.
        </p>
      </footer>
    </main>
  );
}
