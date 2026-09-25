"use client";

import { AlertTriangle, Check, CheckCircle2, CreditCard, ExternalLink, Loader2, Minus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { formatBytes, formatDate } from "@/lib/format";
import { errorMessage, openBillingPortal, startCheckout } from "@/services/api";
import { isSubscribed, useBilling } from "@/services/queries";
import type { Billing, BillingPlan, Entitlements } from "@/types/document";

const MB = 1024 * 1024;
const numberFormat = new Intl.NumberFormat();
// How long to keep asking after Stripe Checkout before saying the plan is still on its way.
const WEBHOOK_WAIT_MS = 60_000;

const STATUS: Record<string, { label: string; tone: "ok" | "warn" | "off" }> = {
  active: { label: "Active", tone: "ok" },
  trialing: { label: "Trial", tone: "ok" },
  past_due: { label: "Payment overdue", tone: "warn" },
  incomplete: { label: "Payment incomplete", tone: "warn" },
  unpaid: { label: "Unpaid", tone: "off" },
  canceled: { label: "Ended", tone: "off" },
  incomplete_expired: { label: "Payment expired", tone: "off" },
  paused: { label: "Paused", tone: "off" },
};
const TONES = {
  ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  warn: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  off: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
};

function count(value: number, word: string): string {
  return `${numberFormat.format(value)} ${word}${value === 1 ? "" : "s"}`;
}

/** What a plan allows, in words; `included: false` is shown struck out. */
function entitlementLines(e: Entitlements): { label: string; included: boolean }[] {
  return [
    { label: e.maxDocuments === null ? "Unlimited documents" : `Up to ${count(e.maxDocuments, "document")}`, included: true },
    { label: `Files up to ${e.maxDocumentSizeMb} MB`, included: true },
    {
      label: e.maxAiOperations === null ? "Unlimited AI operations" : `${count(e.maxAiOperations, "AI operation")} a month`,
      included: e.maxAiOperations !== 0,
    },
    { label: e.maxTemplates === null ? "Unlimited templates" : `${count(e.maxTemplates, "template")} of your own`, included: e.maxTemplates !== 0 },
    { label: e.maxStorageMb === null ? "Unlimited storage" : `${formatBytes(e.maxStorageMb * MB)} of storage`, included: true },
    { label: "Word (.docx) export", included: e.canExportDocx },
    { label: "PDF export", included: e.canExportPdf },
    { label: "Priority processing", included: e.priorityProcessing },
  ];
}

function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Meter({ label, used, limit, format = (n: number) => numberFormat.format(n), note }: {
  label: string;
  used: number;
  limit: number | null;
  format?: (value: number) => string;
  note?: string;
}) {
  const ratio = limit === null ? 0 : limit === 0 ? 1 : Math.min(1, used / limit);
  const tone = limit !== null && used >= limit ? "bg-red-500" : ratio >= 0.8 ? "bg-amber-500" : "bg-accent";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-zinc-700 dark:text-zinc-300">{label}</span>
        <span className="tabular-nums text-zinc-900 dark:text-zinc-50">
          {format(used)} <span className="text-zinc-500 dark:text-zinc-400">{limit === null ? "· unlimited" : `of ${format(limit)}`}</span>
        </span>
      </div>
      {limit !== null && (
        <div
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={Math.min(used, limit)}
          className="mt-1.5 h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800"
        >
          <div className={`h-full rounded-full ${tone}`} style={{ width: `${ratio * 100}%` }} />
        </div>
      )}
      {note && <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{note}</p>}
    </div>
  );
}

function CheckoutNotice({ checkout, billing, timedOut, onDismiss }: {
  checkout: "success" | "cancelled";
  billing: Billing | undefined;
  timedOut: boolean;
  onDismiss: () => void;
}) {
  let tone = "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100";
  let content: ReactNode;
  if (checkout === "cancelled") {
    tone = "border-zinc-200 bg-white text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300";
    content = "Checkout was cancelled. Nothing was charged.";
  } else if (isSubscribed(billing)) {
    content = (
      <span className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /> You&apos;re on {billing?.plan.name} now. Thank you!
      </span>
    );
  } else if (!timedOut) {
    content = (
      <span className="flex items-center gap-2">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" /> Finishing your subscription. This takes a few seconds…
      </span>
    );
  } else {
    tone = "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100";
    content = "Your payment went through, but your plan hasn't switched yet. It can take a minute: reload this page shortly.";
  }
  return (
    <div role="status" className={`mt-6 flex items-start justify-between gap-3 rounded-xl border p-4 text-sm ${tone}`}>
      <div>{content}</div>
      <button type="button" onClick={onDismiss} aria-label="Dismiss" className="rounded-full p-0.5 opacity-70 transition-opacity hover:opacity-100">
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function PlanCard({ plan, billing, busy, onCheckout, onPortal }: {
  plan: BillingPlan;
  billing: Billing;
  busy: string | null;
  onCheckout: (plan: string) => void;
  onPortal: () => void;
}) {
  const current = plan.key === billing.plan.key;
  const buttonClass =
    "mt-5 flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed";
  let action: ReactNode;
  if (current) {
    action = (
      <button type="button" disabled className={`${buttonClass} border border-zinc-200 text-zinc-500 dark:border-zinc-700`}>
        Your plan
      </button>
    );
  } else if (isSubscribed(billing) && billing.canManageBilling) {
    action = (
      <button type="button" onClick={onPortal} disabled={busy !== null} className={`${buttonClass} border border-zinc-300 text-zinc-800 hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-200`}>
        {busy === "portal" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ExternalLink className="h-4 w-4" aria-hidden="true" />}
        Change in billing portal
      </button>
    );
  } else if (plan.available) {
    action = (
      <button type="button" onClick={() => onCheckout(plan.key)} disabled={busy !== null} className={`${buttonClass} bg-accent text-accent-foreground hover:opacity-90 disabled:opacity-60`}>
        {busy === plan.key && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
        Upgrade to {plan.name}
      </button>
    );
  } else {
    action = (
      <button type="button" disabled className={`${buttonClass} border border-dashed border-zinc-300 text-zinc-400 dark:border-zinc-700`}>
        Not available yet
      </button>
    );
  }
  return (
    <article
      aria-label={`${plan.name} plan`}
      className={`flex flex-col rounded-xl border bg-white p-5 shadow-sm dark:bg-zinc-900 ${current ? "border-accent ring-1 ring-accent" : "border-zinc-200 dark:border-zinc-800"}`}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{plan.name}</h3>
        {current && <span className="rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">Current</span>}
      </div>
      <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{plan.priceLabel ?? "Price not set yet"}</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm">
        {entitlementLines(plan.entitlements).map(({ label, included }) => (
          <li key={label} className={`flex items-start gap-2 ${included ? "text-zinc-700 dark:text-zinc-300" : "text-zinc-400 line-through dark:text-zinc-600"}`}>
            {included ? (
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
            ) : (
              <Minus className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            )}
            <span>
              {label}
              {!included && <span className="sr-only"> (not included)</span>}
            </span>
          </li>
        ))}
      </ul>
      {action}
    </article>
  );
}

function BillingDetails({ data, busy, go }: { data: Billing; busy: string | null; go: (action: string, destination: () => Promise<string>) => void }) {
  const status = data.status ? (STATUS[data.status] ?? { label: data.status, tone: "off" as const }) : null;
  return (
    <>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card
          title="Your plan"
          action={
            data.canManageBilling ? (
              <button
                type="button"
                onClick={() => go("portal", openBillingPortal)}
                disabled={busy !== null}
                className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-300"
              >
                {busy === "portal" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <CreditCard className="h-3.5 w-3.5" aria-hidden="true" />}
                Manage billing
              </button>
            ) : undefined
          }
        >
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">{data.plan.name}</p>
            {status && <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONES[status.tone]}`}>{status.label}</span>}
          </div>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            {isSubscribed(data) && data.currentPeriodEnd
              ? data.cancelAtPeriodEnd
                ? `Ends on ${formatDate(data.currentPeriodEnd)}. After that, the free plan's limits apply.`
                : `Renews on ${formatDate(data.currentPeriodEnd)}.`
              : data.status && !isSubscribed(data)
                ? "Your subscription has ended, so the free plan's limits apply."
                : "No subscription."}
          </p>
          {data.status === "past_due" && (
            <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              Your last payment didn&apos;t go through. Update your card in the billing portal to keep your plan.
            </p>
          )}
        </Card>

        <Card title="Usage and limits">
          <div className="space-y-4">
            <Meter label="Documents" used={data.usage.documents.used} limit={data.usage.documents.limit} />
            <Meter
              label="AI operations this month"
              used={data.usage.aiOperations.used}
              limit={data.usage.aiOperations.limit}
              note={`They renew on ${formatDate(data.usagePeriodEnd)}.`}
            />
            <Meter label="Templates of your own" used={data.usage.templates.used} limit={data.usage.templates.limit} />
            <Meter label="Storage" used={data.usage.storageBytes.used} limit={data.usage.storageBytes.limit} format={formatBytes} />
          </div>
        </Card>
      </div>

      <h2 className="mt-10 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Plans</h2>
      {!data.billingEnabled && (
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">Paid plans aren&apos;t available yet. Your plan&apos;s limits apply as shown.</p>
      )}
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {data.plans.map((plan) => (
          <PlanCard
            key={plan.key}
            plan={plan}
            billing={data}
            busy={busy}
            onCheckout={(key) => go(key, () => startCheckout(key))}
            onPortal={() => go("portal", openBillingPortal)}
          />
        ))}
      </div>
      <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">Payments are handled by Stripe. Card details never reach SmartDoc.</p>
    </>
  );
}

/**
 * The workspace's plan (корекции.docx §35): what it allows, how much of that is
 * used, and the plans there are. Subscribing goes through Stripe Checkout and
 * changing or cancelling through Stripe's billing portal; the plan itself only
 * changes when Stripe tells the backend, so after checkout this waits for that.
 */
export function BillingPage({ checkout }: { checkout: "success" | "cancelled" | null }) {
  const router = useRouter();
  const [timedOut, setTimedOut] = useState(false);
  const [showCheckout, setShowCheckout] = useState(checkout !== null);
  const billing = useBilling({ waitForSubscription: checkout === "success" && !timedOut });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checkout !== "success") return;
    const timer = window.setTimeout(() => setTimedOut(true), WEBHOOK_WAIT_MS);
    return () => window.clearTimeout(timer);
  }, [checkout]);

  /** Off to a Stripe-hosted page; `action` shows which button is working. */
  async function go(action: string, destination: () => Promise<string>) {
    setBusy(action);
    setError(null);
    try {
      window.location.assign(await destination());
    } catch (err) {
      setError(errorMessage(err, "That didn't work. Please try again."));
      setBusy(null);
    }
  }

  function dismissCheckout() {
    setShowCheckout(false);
    router.replace("/settings/billing", { scroll: false });
  }

  const data = billing.data;

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Plan and billing</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">What your plan includes, how much of it you&apos;ve used, and the other plans.</p>

        {showCheckout && checkout && <CheckoutNotice checkout={checkout} billing={data} timedOut={timedOut} onDismiss={dismissCheckout} />}
        {error && (
          <p role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error}
          </p>
        )}

        {billing.isPending ? (
          <p className="mt-8 flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
          </p>
        ) : billing.error ? (
          <p className="mt-8 text-sm text-red-600 dark:text-red-400">{errorMessage(billing.error)}</p>
        ) : (
          <BillingDetails data={billing.data} busy={busy} go={go} />
        )}
      </main>
    </div>
  );
}
