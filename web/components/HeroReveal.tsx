"use client";

import { useEffect, useRef } from "react";

/**
 * GSAP word-stagger reveal for the hero headline.
 *
 * Why GSAP here and Motion elsewhere: Motion is React-state-driven and is the
 * right tool for the form and the streaming results. This is a one-shot
 * timeline over DOM nodes that React does not otherwise re-render, which is
 * exactly what GSAP is good at.
 *
 * LCP safety: the text is rendered by the server and is visible in the HTML.
 * We only set the animated-from state AFTER GSAP has loaded on the client, so
 * the headline is never invisible while waiting for a script — if GSAP never
 * arrives, the heading simply sits there, already readable.
 */
export function HeroReveal({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let cancelled = false;
    let tween: { kill: () => void } | undefined;

    void import("gsap").then(({ gsap }) => {
      if (cancelled || !ref.current) return;

      const host = ref.current;
      const text = host.textContent ?? "";
      // Split into words, not characters: a character split on a long headline
      // creates hundreds of nodes and reads as noise to a screen reader if the
      // wrapper is not hidden. aria-label on the parent keeps it announced as
      // one phrase.
      host.setAttribute("aria-label", text);

      // Built with createElement/textContent rather than an innerHTML string.
      // The source here is our own heading, but assembling markup by
      // concatenation is the habit that turns into an XSS the first time the
      // text becomes dynamic.
      const frag = document.createDocumentFragment();
      text.split(" ").forEach((word, i) => {
        if (i > 0) frag.appendChild(document.createTextNode(" "));
        const span = document.createElement("span");
        span.textContent = word;
        span.setAttribute("aria-hidden", "true");
        span.style.display = "inline-block";
        span.style.willChange = "transform, opacity";
        frag.appendChild(span);
      });
      host.replaceChildren(frag);

      const words = host.querySelectorAll("span");
      tween = gsap.from(words, {
        yPercent: 40,
        opacity: 0,
        duration: 0.6,
        stagger: 0.045,
        ease: "power3.out",
        // will-change is a promise to the compositor, not a decoration —
        // clear it once the animation is done so the layers are released.
        onComplete: () => gsap.set(words, { clearProps: "willChange" }),
      });
    });

    return () => {
      cancelled = true;
      tween?.kill();
    };
  }, []);

  return (
    <span ref={ref} className={className}>
      {children}
    </span>
  );
}
