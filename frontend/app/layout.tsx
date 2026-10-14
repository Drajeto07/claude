import type { Metadata } from "next";
import { Geist_Mono, Inter } from "next/font/google";
import { cookies, headers } from "next/headers";

import { I18nProvider } from "@/i18n/I18nProvider";
import { getLocale, getMessages } from "@/i18n/server";
import { NonceProvider } from "@/lib/nonce";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { resolveTheme, THEME_COOKIE } from "@/theme/themes";

import { Providers } from "./providers";
import "./globals.css";

// Inter, not Geist: SmartDoc is used in Bulgarian too, and Geist has no Cyrillic (D-005).
// next/font serves it from this site, so the CSP's font-src 'self' still holds.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin", "cyrillic"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/** The default title and description, in the interface language; pages set their own title. */
export async function generateMetadata(): Promise<Metadata> {
  const m = await getMessages();
  return { title: m.common.appName, description: m.landing.subtitle };
}

// Reading the request's headers makes every page render per request, which the
// nonce in the Content-Security-Policy (proxy.ts) needs: a page built ahead of time
// could not carry it.
export default async function RootLayout({ children }: LayoutProps<"/">) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  // The interface language (D-010): the stored choice, else the browser's language.
  const locale = await getLocale();
  // Light unless this browser chose dark (frontend/theme): never the operating system's choice.
  const theme = resolveTheme((await cookies()).get(THEME_COOKIE)?.value);
  return (
    <html
      lang={locale}
      data-theme={theme}
      className={`${inter.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <NonceProvider nonce={nonce}>
          <I18nProvider locale={locale}>
            <ThemeProvider theme={theme}>
              <Providers>{children}</Providers>
            </ThemeProvider>
          </I18nProvider>
        </NonceProvider>
      </body>
    </html>
  );
}
