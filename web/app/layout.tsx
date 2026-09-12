import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

/**
 * Inter Variable, in two roles.
 *
 * DESIGN.md specifies GT Walsheim Medium for display and Inter Variable for
 * body, and explicitly sanctions the substitution: "suitable open-source
 * substitutes include Mona Sans, Geist, or Inter at weight 600–700 with
 * manually tightened tracking. Inter Variable is open-source — keep it as-is
 * and preserve the documented OpenType variants."
 *
 * One family covering both roles is also the cheapest possible answer to the
 * 2.5s LCP budget: a second display webfont would be pure critical-path cost.
 *
 * NOTE: this replaces Atkinson Hyperlegible. See the handover notes — it is a
 * real trade for low-vision readers, made because DESIGN.md governs here.
 */
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  // 400 body · 500 body-sm/caption/button · 600–700 display substitute.
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ScholarCompass — scholarships and visa rules, without an account",
  description:
    "Find scholarships you are actually eligible for and the visa rules that apply to your passport. No sign-up, no tracking, nothing kept.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // DESIGN.md is dark-only: "Don't ship a light-mode marketing page."
    <html lang="en" className={`${inter.variable} h-full`}>
      <body className="flex min-h-full flex-col bg-canvas text-ink">
        <a href="#main" className="sc-skip-link">
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
