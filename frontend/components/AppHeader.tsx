"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/AccountMenu";
import { Logo } from "@/components/ui/Logo";
import { useI18n } from "@/i18n/I18nProvider";

/**
 * Slim top bar for the screens that keep their own full-width layout (the editor, compare,
 * the create wizard, the public page); the signed-in pages use the sidebar shell
 * (components/shell/AppShell.tsx). Each page renders it itself: editor-specific content
 * (title, export buttons) needs the document object, which layout.tsx doesn't have.
 */
export function AppHeader({ rightSlot }: { rightSlot?: ReactNode }) {
  const { m } = useI18n();
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-line bg-surface px-4 sm:px-6">
      <Link href="/" className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <Logo />
      </Link>
      <div className="flex items-center gap-3">
        {rightSlot}
        <nav aria-label={m.shell.mainNav} className="hidden items-center gap-1 sm:flex">
          {[
            ["/documents", m.shell.projects],
            ["/templates", m.shell.templates],
          ].map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {label}
            </Link>
          ))}
        </nav>
        <AccountMenu />
      </div>
    </header>
  );
}
