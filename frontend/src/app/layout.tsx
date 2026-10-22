import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { NavBar } from "@/components/nav-bar";

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
  title: "TraceMesh",
  description: "Design, run and trace multi-agent workflows.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      {/* Fixed-height shell: the nav takes its height, <main> gets the rest,
          so full-screen pages (the canvas) can fill it without page scroll. */}
      <body className="flex h-dvh flex-col overflow-hidden">
        <NavBar />
        <main className="flex min-h-0 flex-1 flex-col overflow-auto">{children}</main>
      </body>
    </html>
  );
}
