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
 */
export default function Template({ children }: { children: React.ReactNode }) {
  const reduced = useReducedMotion();

  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-1 flex-col"
    >
      {children}
    </motion.div>
  );
}
