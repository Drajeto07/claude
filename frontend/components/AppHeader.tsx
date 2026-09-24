import Link from "next/link";
import { FileText } from "lucide-react";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/AccountMenu";

/**
 * Slim top bar every page renders for itself (not in the root layout) --
 * editor-specific content (title, export buttons) needs the document object,
 * which layout.tsx doesn't have without extra plumbing this app doesn't need.
 */
export function AppHeader({ rightSlot }: { rightSlot?: ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-200 bg-white px-4 dark:border-zinc-800 dark:bg-zinc-950 sm:px-6">
      <Link href="/" className="flex items-center gap-2 text-zinc-900 dark:text-zinc-50">
        <FileText className="h-5 w-5 text-accent" strokeWidth={2.25} aria-hidden="true" />
        <span className="text-sm font-semibold tracking-tight">SmartDoc Formatter</span>
      </Link>
      <div className="flex items-center gap-3">
        {rightSlot}
        <Link
          href="/templates"
          className="hidden rounded-full px-3 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 sm:inline-flex dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
        >
          Templates
        </Link>
        <AccountMenu />
      </div>
    </header>
  );
}
