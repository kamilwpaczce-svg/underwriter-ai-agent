import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Panel underwritera — Mazowiecka Mutual TU",
  description: "Demo panelu underwritera (Etap 4) do agenta AI underwritingu mienia.",
};

// Cala aplikacja jest renderowana po stronie klienta (fetch w komponentach
// "use client" - patrz SPEC_ETAP4.md). Statyczny prerender i instant-navigation
// validation z Cache Components nie maja tu zastosowania (np. useParams() w
// /wnioski/[id] jest z zalozenia dynamiczny) - wylaczamy walidacje dla calego
// drzewa zamiast dodawac Suspense/`use cache`, ktore nie maja tu sensu.
export const instant = false;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="pl"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900">{children}</body>
    </html>
  );
}
