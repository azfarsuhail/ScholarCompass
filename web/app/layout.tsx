import type { Metadata } from "next";
import { Atkinson_Hyperlegible } from "next/font/google";
import "./globals.css";

// Atkinson Hyperlegible was designed by the Braille Institute to maximise
// character distinction for low-vision readers. Self-hosted by next/font, so
// there is no render-blocking request to Google.
const atkinson = Atkinson_Hyperlegible({
  variable: "--font-atkinson",
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ScholarCompass — scholarships and visa rules, without an account",
  description:
    "Find scholarships you are actually eligible for and the visa rules that apply to your passport. No sign-up, no tracking, nothing kept.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${atkinson.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <a href="#main" className="sc-skip-link">
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
