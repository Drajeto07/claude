import { FileText, LayoutTemplate, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/ui/Logo";

/**
 * Screen 1 of SmartDoc 2.0 (docs/SMARTDOC_2_0_SPEC.md §5): a brand panel beside the form on
 * wide screens, the form alone under a slim header on phones. Every claim on the panel is
 * something the app does today.
 */
const POINTS = [
  { icon: FileText, title: "Bring what you have", text: "Paste text or import Word, PDF and plain-text files." },
  { icon: LayoutTemplate, title: "Look right, consistently", text: "Templates and styles give the whole document one clean look." },
  { icon: ShieldCheck, title: "Yours alone", text: "Your documents are private to your account." },
];

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 bg-surface-muted">
      <aside className="relative hidden w-[44%] max-w-xl flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-blue via-indigo-600 to-brand-purple p-10 text-white lg:flex">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-white/10 blur-2xl" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-32 -left-20 h-96 w-96 rounded-full bg-fuchsia-400/20 blur-3xl" />
        <Link href="/" className="relative w-fit rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
          <Logo tone="light" />
        </Link>
        <div className="relative">
          <p className="text-3xl font-semibold leading-tight tracking-tight">Documents and designs that look finished.</p>
          <ul className="mt-8 space-y-5">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3.5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <span>
                  <span className="block font-medium">{title}</span>
                  <span className="block text-sm text-white/80">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/60">© SmartDoc</p>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center px-5 py-4 lg:hidden">
          <Link href="/" className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <Logo />
          </Link>
        </header>
        <main className="flex flex-1 items-center justify-center px-5 py-10 sm:px-8">{children}</main>
      </div>
    </div>
  );
}
