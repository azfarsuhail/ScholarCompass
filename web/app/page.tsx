// Server component. `motion/react-client` animates without pulling the page
// into the client bundle.
import * as motion from "motion/react-client";
import Link from "next/link";

import { HeroReveal } from "@/components/HeroReveal";
import { retentionLabel } from "@/lib/retention";

const PROOF = [
  { figure: "257", label: "programmes crawled live", sub: "Erasmus Mundus · DAAD · Commonwealth · Eiffel" },
  { figure: "<5s", label: "to first results", sub: "before any AI runs" },
  { figure: "0", label: "accounts, ever", sub: `nothing kept after ${retentionLabel}` },
];

const STEPS = [
  {
    n: "01",
    title: "Tell us the basics",
    body: "Six fields, all optional. Or upload a transcript and we read the grades off it — including Pakistani, Indian and German marking schemes that a naive percentage conversion gets wrong.",
  },
  {
    n: "02",
    title: "See what you qualify for",
    body: "Hard rules — nationality, degree level, GPA, deadlines — are checked against the database first. Exact matches are labelled exact. Stretches say precisely what is missing.",
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
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-border">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-[0.35] [background:radial-gradient(60rem_30rem_at_50%_-10%,var(--sc-accent),transparent_70%)]"
        />
        <div className="relative mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          >
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-accent">
              ScholarCompass
            </p>
            <h1 className="mt-4 text-4xl font-bold leading-[1.1] text-balance sm:text-6xl">
              <HeroReveal>Scholarships you can actually get.</HeroReveal>
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground">
              Most search tools show you everything and let you find out you were
              ineligible after the application fee. We check the rules first, then
              send you straight to the official page.
            </p>
          </motion.div>

          <motion.div
            className="mt-9 flex flex-wrap items-center gap-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
          >
            <Link
              href="/start"
              className="inline-flex min-h-12 cursor-pointer items-center justify-center rounded-sc bg-accent px-7 font-bold text-on-accent transition-colors duration-200 hover:bg-primary hover:text-on-primary"
            >
              Find my scholarships
            </Link>
            <span className="text-sm text-muted-foreground">
              No sign-up. About two minutes.
            </span>
          </motion.div>

          {/* Proof row */}
          <motion.dl
            className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-3"
            initial="hidden"
            animate="visible"
            variants={{ visible: { transition: { staggerChildren: 0.08, delayChildren: 0.2 } } }}
          >
            {PROOF.map((p) => (
              <motion.div
                key={p.label}
                variants={{ hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0 } }}
                transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              >
                <dt className="text-3xl font-bold text-foreground">{p.figure}</dt>
                <dd className="mt-1 text-sm text-muted-foreground">
                  {p.label}
                  <span className="block text-xs opacity-80">{p.sub}</span>
                </dd>
              </motion.div>
            ))}
          </motion.dl>
        </div>
      </section>

      {/* How it works */}
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <h2 className="text-2xl font-bold">How it works</h2>
        <ol className="mt-8 flex flex-col gap-8">
          {STEPS.map((s, i) => (
            <motion.li
              key={s.n}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.4, delay: i * 0.05, ease: [0.22, 1, 0.36, 1] }}
              className="flex gap-5 border-l-2 border-border pl-5"
            >
              <div>
                <span className="text-sm font-bold tabular-nums text-accent">{s.n}</span>
                <h3 className="mt-1 text-lg font-bold">{s.title}</h3>
                <p className="mt-2 leading-relaxed text-muted-foreground">{s.body}</p>
              </div>
            </motion.li>
          ))}
        </ol>

        <div className="mt-12 rounded-sc border border-border bg-card p-6">
          <h2 className="font-bold">Why there is no account</h2>
          <p className="mt-2 leading-relaxed text-muted-foreground">
            Your transcript is read in memory and discarded — we keep the grade,
            never the file. Everything else expires within {retentionLabel} on its own,
            and you can erase it instantly at any point. There is no password to
            leak because there is no account to breach.
          </p>
          <Link
            href="/start"
            className="mt-5 inline-flex min-h-11 cursor-pointer items-center font-bold text-accent underline decoration-border underline-offset-4 transition-colors duration-200 hover:decoration-current"
          >
            Start now →
          </Link>
        </div>
      </section>

      <footer className="border-t border-border">
        <p className="mx-auto w-full max-w-3xl px-6 py-8 text-sm text-muted-foreground">
          ScholarCompass gives you sourced information, not immigration advice.
          Confirm with the official embassy or university before you pay anything
          or book travel.
        </p>
      </footer>
    </main>
  );
}
