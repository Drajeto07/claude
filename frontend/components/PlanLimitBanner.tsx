"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useI18n } from "@/i18n/I18nProvider";
import { PLAN_LIMIT_EVENT } from "@/services/api";

/**
 * Whatever the plan refused -- a new document, an export, an AI instruction --
 * and wherever that shows as an error, this offers the way on: the billing
 * page, with the plans and what is used of the current one.
 */
export function PlanLimitBanner() {
  const { m } = useI18n();
  const pathname = usePathname();
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const show = (event: Event) => setMessage((event as CustomEvent<string>).detail);
    window.addEventListener(PLAN_LIMIT_EVENT, show);
    return () => window.removeEventListener(PLAN_LIMIT_EVENT, show);
  }, []);

  if (message === null || pathname === "/settings/billing") return null;

  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-4 z-50 mx-auto flex w-[min(34rem,calc(100%-2rem))] items-start gap-3 rounded-2xl border border-warning/40 bg-warning-soft p-4 shadow-pop"
    >
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-foreground">{m.planLimit.title}</p>
        <p className="mt-0.5 text-foreground">{message}</p>
        <Link href="/settings/billing" onClick={() => setMessage(null)} className="mt-2 inline-block font-medium text-accent hover:underline">
          {m.planLimit.seePlans}
        </Link>
      </div>
      <button
        type="button"
        onClick={() => setMessage(null)}
        aria-label={m.planLimit.dismiss}
        className="rounded-full p-1 text-muted transition-colors hover:bg-surface hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
