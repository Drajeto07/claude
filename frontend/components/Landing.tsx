import Link from "next/link";
import { ClipboardPaste, ShieldCheck, Upload } from "lucide-react";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { buttonClasses } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { getMessages } from "@/i18n/server";

/** The public home page, for someone not signed in: what SmartDoc does, and the way in. Creating
 * something needs an account, so both cards lead to it (and back to the flow afterwards). */
export async function Landing() {
  const m = await getMessages();
  const t = m.landing;
  const cards = [
    { href: "/register?next=%2Fnew", icon: ClipboardPaste, tile: "bg-tile-blue text-tile-blue-ink", ...t.paste },
    { href: "/register?next=%2Fnew%3Fmode%3Dupload", icon: Upload, tile: "bg-tile-teal text-tile-teal-ink", ...t.upload },
  ];

  return (
    <div className="flex min-h-full flex-1 flex-col bg-background">
      <header className="flex h-16 items-center justify-between px-4 sm:px-8">
        <Logo />
        <div className="flex items-center gap-3">
          <LanguageSwitcher compact />
          <Link href="/login" className={buttonClasses({ variant: "ghost", size: "sm" })}>
            {t.signIn}
          </Link>
        </div>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center px-4 py-12 sm:px-6">
        <div className="flex max-w-2xl flex-col items-center gap-5 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">{t.title}</h1>
          <p className="text-lg leading-8 text-muted">{t.subtitle}</p>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <Link href="/register" className={buttonClasses({ size: "lg" })}>
              {t.register}
            </Link>
            <Link href="/login" className={buttonClasses({ variant: "secondary", size: "lg" })}>
              {t.signIn}
            </Link>
          </div>
        </div>

        <div className="mt-12 grid w-full max-w-2xl gap-4 sm:grid-cols-2">
          {cards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="flex flex-col items-start gap-3 rounded-2xl border border-line bg-surface p-6 text-left shadow-card transition-[transform,border-color] hover:-translate-y-0.5 hover:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <span className={`flex h-11 w-11 items-center justify-center rounded-xl ${card.tile}`}>
                <card.icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <span>
                <span className="block text-base font-semibold text-foreground">{card.title}</span>
                <span className="mt-1 block text-sm text-muted">{card.text}</span>
              </span>
            </Link>
          ))}
        </div>

        <p className="mt-8 flex max-w-2xl items-start gap-2 text-left text-sm text-muted">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
          <span>{t.privacy}</span>
        </p>
      </main>
    </div>
  );
}
