import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/AppHeader";
import { DISCLAIMER } from "@/lib/types";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Health Briefing", template: "%s | Health Briefing" },
  description: "Source-cited standard-of-care briefings for health-system strategy teams (POC).",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-canvas text-ink">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <AppHeader />
        <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          {children}
        </main>
        <footer className="no-print mx-auto max-w-7xl px-4 pb-8 text-xs leading-relaxed text-muted sm:px-6">
          <p>
            <strong className="font-semibold text-ink-2">Not medical advice.</strong> {DISCLAIMER}
          </p>
        </footer>
      </body>
    </html>
  );
}
