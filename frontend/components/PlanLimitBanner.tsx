"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { PLAN_LIMIT_EVENT } from "@/services/api";

/**
 * Whatever the plan refused -- a new document, an export, an AI instruction --
 * and wherever that shows as an error, this offers the way on: the billing
 * page, with the plans and what is used of the current one.
 */
export function PlanLimitBanner() {
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
      className="fixed inset-x-0 bottom-4 z-50 mx-auto flex w-[min(34rem,calc(100%-2rem))] items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 shadow-lg dark:border-amber-800 dark:bg-amber-950"
    >
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-amber-950 dark:text-amber-100">Your plan&apos;s limit</p>
        <p className="mt-0.5 text-amber-900 dark:text-amber-200">{message}</p>
        <Link href="/settings/billing" onClick={() => setMessage(null)} className="mt-2 inline-block font-medium text-accent hover:underline">
          See plans and usage
        </Link>
      </div>
      <button
        type="button"
        onClick={() => setMessage(null)}
        aria-label="Dismiss"
        className="rounded-full p-1 text-amber-800 transition-colors hover:bg-amber-100 dark:text-amber-200 dark:hover:bg-amber-900"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
