"use client";

import { AlertTriangle, Check, CheckCircle2, CreditCard, ExternalLink, Loader2, Minus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { Notice } from "@/components/ui/Notice";
import { formatDate } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { formatBytes } from "@/lib/format";
import { errorMessage, openBillingPortal, startCheckout } from "@/services/api";
import { isSubscribed, useBilling } from "@/services/queries";
import type { Billing, BillingPlan, Entitlements, UnitUsage } from "@/types/document";

type Words = Messages["billing"];

const MB = 1024 * 1024;
// How long to keep asking after Stripe Checkout before saying the plan is still on its way.
const WEBHOOK_WAIT_MS = 60_000;

const STATUS_TONES: Record<string, "ok" | "warn" | "off"> = {
  active: "ok",
  trialing: "ok",
  past_due: "warn",
  incomplete: "warn",
  unpaid: "off",
  canceled: "off",
  incomplete_expired: "off",
  paused: "off",
};
const TONES = {
  ok: "bg-success/10 text-success",
  warn: "bg-warning-soft text-warning",
  off: "bg-surface-muted text-muted",
};

function useNumbers() {
  const { locale } = useI18n();
  return new Intl.NumberFormat(locale);
}

/** A unit's name in the interface language; the server's own label for one this version doesn't know. */
function unitLabel(unit: UnitUsage, t: Words): string {
  const units: Record<string, string> = t.units;
  return units[unit.key] ?? unit.label;
}

/** What a plan allows, in words; `included: false` is shown struck out. */
function entitlementLines(e: Entitlements, t: Words, numbers: Intl.NumberFormat): { label: string; included: boolean }[] {
  const lines = t.lines;
  const counted = (value: number, forms: { one: string; other: string }) => plural(value, forms, { count: numbers.format(value) });
  return [
    { label: e.maxDocuments === null ? lines.unlimitedDocuments : counted(e.maxDocuments, lines.documents), included: true },
    { label: format(lines.fileSize, { mb: e.maxDocumentSizeMb }), included: true },
    { label: e.maxExports === null ? lines.unlimitedExports : counted(e.maxExports, lines.exports), included: e.maxExports !== 0 },
    { label: e.maxPdfPages === null ? lines.unlimitedPdfPages : counted(e.maxPdfPages, lines.pdfPages), included: e.maxPdfPages !== 0 },
    { label: e.maxAiOperations === null ? lines.unlimitedAi : counted(e.maxAiOperations, lines.ai), included: e.maxAiOperations !== 0 },
    { label: e.maxTemplates === null ? lines.unlimitedTemplates : counted(e.maxTemplates, lines.templates), included: e.maxTemplates !== 0 },
    { label: e.maxStorageMb === null ? lines.unlimitedStorage : format(lines.storage, { size: formatBytes(e.maxStorageMb * MB) }), included: true },
    { label: lines.docx, included: e.canExportDocx },
    { label: lines.pdf, included: e.canExportPdf },
    { label: lines.priority, included: e.priorityProcessing },
  ];
}

/** The units whose features don't exist yet: the plan's limit for each; nothing counts them. */
function ComingLater({ units }: { units: UnitUsage[] }) {
  const { m } = useI18n();
  const t = m.billing;
  const numbers = useNumbers();
  if (units.length === 0) return null;
  return (
    <div className="mt-5 border-t border-line pt-4">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted">{t.comingLater}</h3>
      <ul className="mt-2 space-y-1 text-sm text-muted">
        {units.map((unit) => (
          <li key={unit.key} className="flex items-baseline justify-between gap-3">
            <span>{unitLabel(unit, t)}</span>
            <span className="tabular-nums">{unit.limit === null ? t.unlimited : unit.limit === 0 ? t.notIncluded : format(t.aMonth, { count: numbers.format(unit.limit) })}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Meter({ label, used, limit, show }: { label: string; used: number; limit: number | null; show: (value: number) => string }) {
  const { m } = useI18n();
  const ratio = limit === null ? 0 : limit === 0 ? 1 : Math.min(1, used / limit);
  const tone = limit !== null && used >= limit ? "bg-danger" : ratio >= 0.8 ? "bg-warning" : "bg-accent";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-foreground">{label}</span>
        <span className="tabular-nums text-foreground">
          {show(used)} <span className="text-muted">{limit === null ? m.billing.unlimitedShort : format(m.billing.ofLimit, { limit: show(limit) })}</span>
        </span>
      </div>
      {limit !== null && (
        <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={limit} aria-valuenow={Math.min(used, limit)} className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-muted">
          <div className={`h-full rounded-full ${tone}`} style={{ width: `${ratio * 100}%` }} />
        </div>
      )}
    </div>
  );
}

function CheckoutNotice({ checkout, billing, timedOut, onDismiss }: { checkout: "success" | "cancelled"; billing: Billing | undefined; timedOut: boolean; onDismiss: () => void }) {
  const { m } = useI18n();
  const t = m.billing;
  let tone = "border-success/30 bg-success/10 text-foreground";
  let content: ReactNode;
  if (checkout === "cancelled") {
    tone = "border-line bg-surface text-foreground";
    content = t.checkout.cancelled;
  } else if (isSubscribed(billing)) {
    content = (
      <span className="flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" /> {format(t.checkout.done, { plan: billing?.plan.name ?? "" })}
      </span>
    );
  } else if (!timedOut) {
    content = (
      <span className="flex items-center gap-2">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" /> {t.checkout.finishing}
      </span>
    );
  } else {
    tone = "border-warning/40 bg-warning-soft text-foreground";
    content = t.checkout.delayed;
  }
  return (
    <div role="status" className={`mt-6 flex items-start justify-between gap-3 rounded-2xl border p-4 text-sm ${tone}`}>
      <div>{content}</div>
      <button type="button" onClick={onDismiss} aria-label={t.dismiss} className="rounded-full p-0.5 opacity-70 transition-opacity hover:opacity-100">
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function PlanCard({ plan, billing, busy, onCheckout, onPortal }: { plan: BillingPlan; billing: Billing; busy: string | null; onCheckout: (plan: string) => void; onPortal: () => void }) {
  const { m } = useI18n();
  const t = m.billing;
  const numbers = useNumbers();
  const current = plan.key === billing.plan.key;
  const buttonClass = "mt-5 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed";
  let action: ReactNode;
  if (current) {
    action = (
      <button type="button" disabled className={`${buttonClass} border border-line text-muted`}>
        {t.yourPlanButton}
      </button>
    );
  } else if (isSubscribed(billing) && billing.canManageBilling) {
    action = (
      <button type="button" onClick={onPortal} disabled={busy !== null} className={`${buttonClass} border border-line-strong text-foreground hover:border-accent hover:text-accent`}>
        {busy === "portal" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ExternalLink className="h-4 w-4" aria-hidden="true" />}
        {t.changeInPortal}
      </button>
    );
  } else if (plan.available) {
    action = (
      <button
        type="button"
        onClick={() => onCheckout(plan.key)}
        disabled={busy !== null}
        className={`${buttonClass} bg-gradient-to-r from-brand-blue to-brand-purple text-white hover:brightness-110 disabled:opacity-60`}
      >
        {busy === plan.key && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {format(t.upgrade, { name: plan.name })}
      </button>
    );
  } else {
    action = (
      <button type="button" disabled className={`${buttonClass} border border-dashed border-line-strong text-muted`}>
        {t.notAvailable}
      </button>
    );
  }
  return (
    <article aria-label={format(t.planName, { name: plan.name })} className={`flex flex-col rounded-2xl border bg-surface p-5 shadow-card ${current ? "border-accent ring-1 ring-accent" : "border-line"}`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-foreground">{plan.name}</h3>
        {current && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">{t.current}</span>}
      </div>
      <p className="mt-1 text-sm text-muted">{plan.priceLabel ?? t.noPrice}</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm">
        {entitlementLines(plan.entitlements, t, numbers).map(({ label, included }) => (
          <li key={label} className={`flex items-start gap-2 ${included ? "text-foreground" : "text-muted line-through"}`}>
            {included ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" /> : <Minus className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
            <span>
              {label}
              {!included && <span className="sr-only">{t.notIncludedSr}</span>}
            </span>
          </li>
        ))}
      </ul>
      {action}
    </article>
  );
}

function BillingDetails({ data, busy, go }: { data: Billing; busy: string | null; go: (action: string, destination: () => Promise<string>) => void }) {
  const { m, locale } = useI18n();
  const t = m.billing;
  const numbers = useNumbers();
  const statuses: Record<string, string> = t.status;
  const status = data.status ? { label: statuses[data.status] ?? data.status, tone: STATUS_TONES[data.status] ?? "off" } : null;
  const date = (iso: string) => formatDate(iso, locale);
  return (
    <>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card
          title={t.yourPlan}
          action={
            data.canManageBilling ? (
              <button
                type="button"
                onClick={() => go("portal", openBillingPortal)}
                disabled={busy !== null}
                className="flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-accent hover:text-accent disabled:opacity-60"
              >
                {busy === "portal" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <CreditCard className="h-3.5 w-3.5" aria-hidden="true" />}
                {t.manage}
              </button>
            ) : undefined
          }
        >
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-2xl font-semibold text-foreground">{data.plan.name}</p>
            {status && <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONES[status.tone]}`}>{status.label}</span>}
          </div>
          <p className="mt-1 text-sm text-muted">
            {isSubscribed(data) && data.currentPeriodEnd
              ? data.cancelAtPeriodEnd
                ? format(t.endsOn, { date: date(data.currentPeriodEnd) })
                : format(t.renewsOn, { date: date(data.currentPeriodEnd) })
              : data.status && !isSubscribed(data)
                ? t.ended
                : t.noSubscription}
          </p>
          {data.status === "past_due" && (
            <p className="mt-3 flex items-start gap-2 rounded-xl border border-warning/40 bg-warning-soft p-3 text-sm text-foreground">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
              {t.pastDue}
            </p>
          )}
        </Card>

        <Card title={t.usage}>
          <div className="space-y-4">
            {data.units
              .filter((unit) => unit.available)
              .map((unit) => (
                <Meter
                  key={unit.key}
                  label={unit.period === "month" ? format(t.thisMonth, { label: unitLabel(unit, t) }) : unitLabel(unit, t)}
                  used={unit.used}
                  limit={unit.limit}
                  show={unit.measure === "bytes" ? formatBytes : (value) => numbers.format(value)}
                />
              ))}
          </div>
          <p className="mt-4 text-xs text-muted">{format(t.renew, { date: date(data.usagePeriodEnd) })}</p>
          <ComingLater units={data.units.filter((unit) => !unit.available)} />
        </Card>
      </div>

      <h2 className="mt-10 text-lg font-semibold text-foreground">{t.plans}</h2>
      {!data.billingEnabled && <p className="mt-1 text-sm text-muted">{t.notEnabled}</p>}
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {data.plans.map((plan) => (
          <PlanCard key={plan.key} plan={plan} billing={data} busy={busy} onCheckout={(key) => go(key, () => startCheckout(key))} onPortal={() => go("portal", openBillingPortal)} />
        ))}
      </div>
      <p className="mt-4 text-xs text-muted">{t.stripeNote}</p>
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
  const { m } = useI18n();
  const t = m.billing;
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
      setError(errorMessage(err, t.failed));
      setBusy(null);
    }
  }

  function dismissCheckout() {
    setShowCheckout(false);
    router.replace("/settings/billing", { scroll: false });
  }

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{t.title}</h1>
        <p className="mt-1 text-sm text-muted">{t.subtitle}</p>

        {showCheckout && checkout && <CheckoutNotice checkout={checkout} billing={billing.data} timedOut={timedOut} onDismiss={dismissCheckout} />}
        {error && (
          <div className="mt-6">
            <Notice tone="error">{error}</Notice>
          </div>
        )}

        {billing.isPending ? (
          <p className="mt-8 flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {m.common.loading}
          </p>
        ) : billing.error ? (
          <div className="mt-8">
            <Notice tone="error">{errorMessage(billing.error)}</Notice>
          </div>
        ) : (
          <BillingDetails data={billing.data} busy={busy} go={go} />
        )}
      </main>
    </AppShell>
  );
}
