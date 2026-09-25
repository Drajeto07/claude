"use client";

import { Home, X } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

export type SidePanelTab = {
  id: string;
  label: string;
  icon: ReactNode;
  content: ReactNode;
};

/**
 * Icon-tab rail + flyout, the progressive-disclosure pattern from the audit:
 * canvas width stays reclaimed until a panel is actually needed. Click a tab
 * to open its flyout; click the same tab (or the flyout's close button) to
 * close it again. An optional leading "Home" link (a real navigation, not a
 * flyout) matches the master-prompt screenshot's app-shell rail without
 * inventing separate routes for what are, everywhere else, in-editor panels.
 * Below 1100 px the flyout opens over the content beside it rather than
 * squeezing it (the parent must be positioned).
 */
export function SidePanel({
  tabs,
  defaultTabId,
  showHomeLink = false,
}: {
  tabs: SidePanelTab[];
  defaultTabId?: string | null;
  showHomeLink?: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(defaultTabId ?? null);
  const openTab = tabs.find((tab) => tab.id === openId) ?? null;

  return (
    <div className="flex shrink-0">
      <nav className="flex w-16 shrink-0 flex-col items-center gap-1 border-r border-zinc-200 bg-white py-3 dark:border-zinc-800 dark:bg-zinc-950">
        {showHomeLink && (
          <>
            <Link
              href="/"
              title="Начало"
              aria-label="Начало"
              className="flex h-11 w-11 flex-col items-center justify-center gap-0.5 rounded-lg text-[10px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-200"
            >
              <Home className="h-[18px] w-[18px]" aria-hidden="true" />
              Начало
            </Link>
            <span className="my-1 h-px w-8 bg-zinc-200 dark:bg-zinc-800" aria-hidden="true" />
          </>
        )}
        {tabs.map((tab) => {
          const active = tab.id === openId;
          return (
            <button
              key={tab.id}
              type="button"
              title={tab.label}
              aria-label={tab.label}
              aria-pressed={active}
              onClick={() => setOpenId(active ? null : tab.id)}
              className={`flex h-11 w-11 flex-col items-center justify-center gap-0.5 rounded-lg text-[10px] font-medium transition-colors ${
                active
                  ? "bg-accent/10 text-accent"
                  : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-200"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
      </nav>
      {openTab && (
        <div className="absolute inset-y-0 left-16 z-30 flex w-80 max-w-[calc(100vw-5rem)] shrink-0 flex-col border-r border-zinc-200 bg-white shadow-xl min-[1100px]:static min-[1100px]:max-w-none min-[1100px]:shadow-none dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">{openTab.label}</h2>
            <button
              type="button"
              aria-label={`Close ${openTab.label}`}
              onClick={() => setOpenId(null)}
              className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{openTab.content}</div>
        </div>
      )}
    </div>
  );
}
