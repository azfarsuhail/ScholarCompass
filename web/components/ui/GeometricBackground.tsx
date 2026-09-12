"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";

/**
 * Wireframe geometry behind the hero.
 *
 * DESIGN.md compliance:
 *  - Stroke only. No fills, no gradients, no background colour — "Don't apply
 *    gradient backgrounds to whole sections" and the gradient family is
 *    reserved for spotlight CARDS.
 *  - The stroke is {colors.ink-muted}, so this introduces no second chromatic
 *    accent: "Don't combine more than one chromatic accent."
 *  - Sits at low opacity behind the content, so the ink / ink-muted contrast
 *    that carries hierarchy on this canvas is unaffected.
 *
 * On the stroke colour: `--color-ink-muted` is declared inside `@theme inline`,
 * and the `inline` option makes Tailwind substitute the value into utilities
 * rather than emitting the custom property. A bare var(--color-ink-muted)
 * therefore resolves to nothing and the stroke falls back to black — invisible
 * on a #090909 canvas. The `--fr-ink-muted` fallback is the token that is
 * actually defined at :root, so the intended colour renders either way.
 */

const STROKE = "var(--color-ink-muted, var(--fr-ink-muted, #999999))";

export function GeometricBackground() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      // gsap.matchMedia handles the reduced-motion branch AND reverts every
      // tween it created when the preference changes — no manual teardown.
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // svgOrigin, not transformOrigin: a percentage origin on an SVG node
        // makes GSAP call getBBox() to resolve it, which forces a layout read
        // on every tween it sets up. Every shape here is centred on 400,400 in
        // the viewBox, so stating that directly skips the measurement — this
        // was worth ~200ms of LCP render delay in a production trace.
        //
        // Counter-rotating rings read as depth without any shadow or fill.
        gsap.to("[data-ring='outer']", {
          rotation: 360,
          duration: 140,
          repeat: -1,
          ease: "none",
          svgOrigin: "400 400",
        });
        gsap.to("[data-ring='mid']", {
          rotation: -360,
          duration: 100,
          repeat: -1,
          ease: "none",
          svgOrigin: "400 400",
        });
        gsap.to("[data-ring='inner']", {
          rotation: 360,
          duration: 70,
          repeat: -1,
          ease: "none",
          svgOrigin: "400 400",
        });

        // The slow breath. yoyo keeps it continuous without a visible reset.
        gsap.to("[data-scale]", {
          scale: 1.12,
          duration: 16,
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
          svgOrigin: "400 400",
        });
      });

      return () => mm.revert();
    },
    { scope: root },
  );

  return (
    <div
      ref={root}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
    >
      <svg
        viewBox="0 0 800 800"
        // Deliberately oversized and centre-anchored so the rotation never
        // sweeps an empty corner into view.
        className="absolute top-1/2 left-1/2 h-[140%] w-[140%] -translate-x-1/2 -translate-y-1/2"
        fill="none"
        stroke={STROKE}
        vectorEffect="non-scaling-stroke"
      >
        <g data-scale opacity="0.14">
          {/* Outer hexagon */}
          <g data-ring="outer">
            <polygon
              points="400,90 669,245 669,555 400,710 131,555 131,245"
              strokeWidth="1"
            />
            <circle cx="400" cy="400" r="310" strokeWidth="0.75" strokeDasharray="3 9" />
          </g>

          {/* Mid triangle pair */}
          <g data-ring="mid">
            <polygon points="400,160 608,520 192,520" strokeWidth="1" />
            <polygon points="400,640 192,280 608,280" strokeWidth="1" />
          </g>

          {/* Inner square + circle */}
          <g data-ring="inner">
            <rect x="265" y="265" width="270" height="270" strokeWidth="1" />
            <circle cx="400" cy="400" r="135" strokeWidth="0.75" />
          </g>
        </g>
      </svg>
    </div>
  );
}
