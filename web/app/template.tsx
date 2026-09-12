"use client";

import { motion, useReducedMotion } from "motion/react";

/**
 * Page transition seam.
 *
 * template.tsx (not layout.tsx) because Next remounts a template on every
 * navigation, which is exactly the lifecycle Motion needs to replay an enter
 * animation. App Router unmounts the old page before the new one commits, so
 * there is no honest exit animation to run — we animate in only, rather than
 * faking a crossfade that would delay the new page.
 *
 * The first pass used opacity + 8px over 0.28s, which was too slight to read
 * as a transition at all. A spring with real displacement and a touch of
 * scale makes navigation feel like movement without costing meaningful time.
 */
export default function Template({ children }: { children: React.ReactNode }) {
  const reduced = useReducedMotion();

  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y: 20, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 28, mass: 0.9 }}
      className="flex flex-1 flex-col"
    >
      {children}
    </motion.div>
  );
}
