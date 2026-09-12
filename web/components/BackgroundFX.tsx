"use client";

import { useEffect, useRef } from "react";

/**
 * Ambient animated background, driven by GSAP.
 *
 * Tuning note: the first version drifted ±6% over 14–22s at 0.18 alpha, which
 * was technically animating and visually indistinguishable from a static
 * gradient. Motion you cannot perceive is just cost. The values below are
 * deliberately large enough to read as alive at a glance while staying behind
 * content and well under the contrast floor.
 *
 * Still non-negotiable:
 *  - GSAP is imported dynamically inside the effect, so it never enters the
 *    initial bundle or delays the LCP element.
 *  - prefers-reduced-motion gets one static paint and no ticker at all.
 *  - Fixed, behind everything, pointer-events:none, aria-hidden.
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
    // (and the dark-mode swap) rather than hardcoding a second set of colours.
    const styles = getComputedStyle(document.documentElement);
    const pick = (name: string, fallback: string) =>
      styles.getPropertyValue(name).trim() || fallback;

    const accent = pick("--sc-accent", "#0369a1");
    const near = pick("--sc-near", accent);
    const exact = pick("--sc-exact", "#047857");
    const stretch = pick("--sc-stretch", "#b45309");

    const blobs = [
      { x: 0.18, y: 0.18, r: 320, c: accent, a: 0.34 },
      { x: 0.82, y: 0.12, r: 280, c: near, a: 0.3 },
      { x: 0.55, y: 0.78, r: 360, c: exact, a: 0.26 },
      { x: 0.1, y: 0.72, r: 240, c: stretch, a: 0.2 },
    ].map((b) => ({ ...b, ox: b.x, oy: b.y, or: b.r }));

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
        const r = Math.max(1, b.r * dpr);
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, b.c);
        g.addColorStop(1, "transparent");
        ctx.globalAlpha = b.a;
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
      // One static paint, no ticker. A rAF loop running forever is its own
      // accessibility problem, so we do not start one at all.
      return () => window.removeEventListener("resize", resize);
    }

    let cleanupGsap: (() => void) | undefined;
    let cancelled = false;

    void import("gsap").then(({ gsap }) => {
      if (cancelled) return;

      const tweens = blobs.flatMap((b, i) => [
        gsap.to(b, {
          // Large enough to actually see. Roughly a fifth of the viewport,
          // versus the 6% that read as static.
          x: b.ox + gsap.utils.random(-0.2, 0.2),
          y: b.oy + gsap.utils.random(-0.18, 0.18),
          duration: gsap.utils.random(7, 11),
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
          delay: i * 0.4,
        }),
        // Breathing radius gives the gradient visible life even where a blob
        // is drifting mostly off-screen.
        gsap.to(b, {
          r: b.or * gsap.utils.random(1.25, 1.5),
          duration: gsap.utils.random(5, 8),
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
          delay: i * 0.3,
        }),
      ]);

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
      className="pointer-events-none fixed inset-0 -z-10"
    />
  );
}
