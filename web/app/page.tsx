// Server component. Motion's `react-client` entrypoint animates without
// pulling this page into the client bundle.
import * as motion from "motion/react-client";
import Link from "next/link";

const BENEFITS = [
  {
    title: "Eligibility first, opinions second",
    body: "Hard rules — nationality, degree level, GPA, deadlines — are checked deterministically before any AI is involved. If you are not eligible, no model gets to talk you into it.",
  },
  {
    title: "Visa rules with receipts",
    body: "Every visa answer carries its source and the date it was last verified. Nothing is asserted without a citation you can open and check yourself.",
  },
  {
    title: "Nothing kept",
    body: "No account, no password, no email. Your transcript is read in memory and discarded, and everything else expires on its own within 72 hours.",
  },
];

export default function Home() {
  return (
    <main id="main" className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-6 py-16">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      >
        <p className="text-sm font-bold uppercase tracking-wider text-accent">
          ScholarCompass
        </p>
        <h1 className="mt-3 text-4xl font-bold leading-tight sm:text-5xl">
          Scholarships you can actually get. Visa rules you can actually trust.
        </h1>
        <p className="mt-5 text-lg text-muted-foreground">
          Answer a few questions — or upload a transcript and skip most of them.
          No account required, because we did not build one.
        </p>
      </motion.div>

      <motion.ul
        className="mt-12 flex flex-col gap-6"
        initial="hidden"
        animate="visible"
        variants={{
          visible: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } },
        }}
      >
        {BENEFITS.map((b) => (
          <motion.li
            key={b.title}
            variants={{
              hidden: { opacity: 0, y: 12 },
              visible: { opacity: 1, y: 0 },
            }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="rounded-sc border border-border bg-card p-5"
          >
            <h2 className="font-bold text-card-foreground">{b.title}</h2>
            <p className="mt-2 text-muted-foreground">{b.body}</p>
          </motion.li>
        ))}
      </motion.ul>

      <div className="mt-12">
        <Link
          href="/match"
          className="inline-flex min-h-11 cursor-pointer items-center justify-center rounded-sc bg-accent px-6 py-3 font-bold text-on-accent transition-colors duration-200 hover:bg-primary hover:text-on-primary"
        >
          Find my scholarships
        </Link>
        <p className="mt-3 text-sm text-muted-foreground">
          Takes about two minutes. You can leave at any point and nothing is saved.
        </p>
      </div>

      <footer className="mt-auto pt-16 text-sm text-muted-foreground">
        <p>
          ScholarCompass gives you sourced information, not immigration advice.
          Always confirm with the official embassy or university before you pay
          anything or book travel.
        </p>
      </footer>
    </main>
  );
}
