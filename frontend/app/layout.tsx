import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";

import { NonceProvider } from "@/lib/nonce";

import { Providers } from "./providers";
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
  title: "SmartDoc Formatter",
  description: "Paste raw text and get back a structured, editable document.",
};

// Reading the request's headers makes every page render per request, which the
// nonce in the Content-Security-Policy (proxy.ts) needs: a page built ahead of time
// could not carry it.
export default async function RootLayout({ children }: LayoutProps<"/">) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <NonceProvider nonce={nonce}>
          <Providers>{children}</Providers>
        </NonceProvider>
      </body>
    </html>
  );
}
