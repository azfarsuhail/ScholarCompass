"use client";

import { useEffect, useRef } from "react";

/**
 * Ambient background, animated with GSAP.
 *
 * Three constraints shape this, and they are why it is a canvas of a few soft
 * blobs rather than anything showier:
 *
 *  1. LCP budget. GSAP is imported dynamically INSIDE the effect, so it never
 *     enters the initial bundle or the critical path — the hero text paints
 *     first and this fades in afterwards.
 *  2. It must never compete with content. Fixed, behind everything,
 *     pointer-events:none, aria-hidden, and low opacity, so it cannot touch
 *     the 4.5:1 contrast of any text above it.
 *  3. prefers-reduced-motion gets a single static paint and no ticker at all.
 *     Bailing out of the animation is not enough — a rAF loop running forever
 *     on a laptop is its own accessibility problem.
 */
export function BackgroundFX() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Read the palette from CSS variables so the background follows the theme
    // (and the dark-mode swap) instead of hardcoding a second set of colours.
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--sc-accent").trim() || "#0369a1";
    const near = styles.getPropertyValue("--sc-near").trim() || accent;
    const exact = styles.getPropertyValue("--sc-exact").trim() || accent;

    const blobs = [
      { x: 0.2, y: 0.15, r: 260, c: accent },
      { x: 0.8, y: 0.1, r: 220, c: near },
      { x: 0.5, y: 0.75, r: 300, c: exact },
    ].map((b) => ({ ...b, ox: b.x, oy: b.y }));

    let dpr = 1;
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2); // 2 is plenty; 3 is wasted fill
      canvas.width = Math.floor(window.innerWidth * dpr);
      canvas.height = Math.floor(window.innerHeight * dpr);
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
    };

    const draw = () => {
      const { width: w, height: h } = canvas;
      ctx.clearRect(0, 0, w, h);
      for (const b of blobs) {
        const cx = b.x * w;
        const cy = b.y * h;
        const r = b.r * dpr;
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, b.c);
        g.addColorStop(1, "transparent");
        ctx.globalAlpha = 0.18;
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    resize();
    draw();
    window.addEventListener("resize", resize);

    if (reduced) {
      // One static paint, no ticker. Nothing to clean up but the listener.
      return () => window.removeEventListener("resize", resize);
    }

    let cleanupGsap: (() => void) | undefined;
    let cancelled = false;

    // Dynamic import: keeps GSAP out of the initial bundle so it cannot delay
    // first paint. If it never loads, the static gradient above still stands.
    void import("gsap").then(({ gsap }) => {
      if (cancelled) return;

      const tweens = blobs.map((b, i) =>
        gsap.to(b, {
          // Deliberately tiny drift. This is atmosphere, not a focal point;
          // anything larger pulls the eye away from the form.
          x: b.ox + gsap.utils.random(-0.06, 0.06),
          y: b.oy + gsap.utils.random(-0.05, 0.05),
          duration: gsap.utils.random(14, 22),
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
          delay: i * 1.5,
        }),
      );

      gsap.ticker.add(draw);
      // 30fps is imperceptible for a slow drift and halves the paint cost on
      // the low-end laptops a student is most likely using.
      gsap.ticker.fps(30);

      cleanupGsap = () => {
        gsap.ticker.remove(draw);
        tweens.forEach((t) => t.kill());
      };
    });

    return () => {
      cancelled = true;
      window.removeEventListener("resize", resize);
      cleanupGsap?.();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 opacity-70"
    />
  );
}
