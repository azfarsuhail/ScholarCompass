"use client";

import { useEffect, useRef } from "react";

type Props = {
  children: React.ReactNode;
  className?: string;
  /** CSS selector for children to stagger. Omit to animate the wrapper itself. */
  stagger?: string;
  /** Animate on mount instead of on scroll. Use above the fold. */
  immediate?: boolean;
  delay?: number;
};

/**
 * GSAP entrance animation for a block or a set of children.
 *
 * Scroll-triggered by default via ScrollTrigger (bundled with GSAP since 3.13,
 * no Club licence needed). Motion still owns state-driven UI — the form, the
 * streaming results — because it re-renders with React. This owns one-shot
 * entrances over DOM that React is not otherwise touching.
 *
 * Content is visible in the server-rendered HTML and is only hidden once GSAP
 * has actually loaded. If the script never arrives, the section simply sits
 * there readable rather than stuck at opacity 0 — the failure mode that makes
 * scroll animations a liability.
 */
export function Reveal({
  children,
  className,
  stagger,
  immediate = false,
  delay = 0,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let cancelled = false;
    let cleanup: (() => void) | undefined;

    void (async () => {
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
      ]);
      if (cancelled || !ref.current) return;

      gsap.registerPlugin(ScrollTrigger);

      const targets = stagger
        ? Array.from(ref.current.querySelectorAll<HTMLElement>(stagger))
        : [ref.current];
      if (!targets.length) return;

      const tween = gsap.from(targets, {
        y: 28,
        opacity: 0,
        duration: 0.7,
        ease: "power3.out",
        stagger: stagger ? 0.1 : 0,
        delay,
        ...(immediate
          ? {}
          : {
              scrollTrigger: {
                trigger: ref.current,
                // Fire a little before the block is fully on screen, so the
                // motion is seen rather than finished by the time you look.
                start: "top 85%",
                once: true,
              },
            }),
      });

      cleanup = () => {
        tween.scrollTrigger?.kill();
        tween.kill();
      };
    })();

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [stagger, immediate, delay]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
