"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { buttonClasses } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { useI18n } from "@/i18n/I18nProvider";
import { confirmEmailVerification, requestEmailVerification } from "@/services/api";
import { queryKeys, useEmailDelivery } from "@/services/queries";

/**
 * Confirming an address (ACCT-003): the dashboard's notice while it isn't confirmed,
 * with another link on request, and the page the link opens. The token is in the
 * link's fragment, which no request carries; it is sent when the person confirms.
 */

export function VerifyEmailBanner({ email }: { email: string }) {
  const { m } = useI18n();
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Only once the server says it sends e-mail (RELEASE): otherwise no link went out, nor could one.
  const { data: emailDelivers } = useEmailDelivery();
  if (emailDelivers !== true) return null;

  async function sendAgain() {
    setBusy(true);
    setError(null);
    try {
      await requestEmailVerification();
      setSent(m.verify.sent);  // in the interface language; the API's own message is English
    } catch {
      setError(m.auth.errors.generic);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="region"
      aria-label={m.verify.region}
      className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-foreground"
    >
      <p>
        {sent ?? (
          <>
            {m.verify.promptStart} <strong className="font-medium">{email}</strong>
            {m.verify.promptEnd}
          </>
        )}
        {error && <span className="ml-1 text-danger">{error}</span>}
      </p>
      {!sent && (
        <button
          type="button"
          onClick={sendAgain}
          disabled={busy}
          className="shrink-0 rounded-full bg-warning px-3 py-1 text-xs font-medium text-surface hover:brightness-110 disabled:opacity-60"
        >
          {busy ? m.verify.sending : m.verify.send}
        </button>
      )}
    </div>
  );
}

const TOKEN = /(?:^#|&)token=([A-Za-z0-9_-]+)/;

function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

const cardClass = "flex w-full max-w-md flex-col gap-5 rounded-2xl border border-line bg-surface p-7 shadow-card sm:p-9";
const buttonClass = buttonClasses({ size: "lg", block: true });

/** The page the link opens: one click confirms, so a mail scanner that opens links confirms nothing. */
export function VerifyEmailForm() {
  const { m } = useI18n();
  const t = m.verifyPage;
  const queryClient = useQueryClient();
  const hasToken = useSyncExternalStore(
    subscribeToHash,
    () => TOKEN.test(window.location.hash),
    () => true,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function confirm() {
    const token = TOKEN.exec(window.location.hash)?.[1];
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await confirmEmailVerification(token);
      window.history.replaceState(null, "", window.location.pathname);
      // The dashboard's notice goes: whoever is signed in here is asked again who they are.
      await queryClient.invalidateQueries({ queryKey: queryKeys.currentUser });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.somethingWrong);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cardClass}>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{done ? t.confirmedTitle : t.title}</h1>
      {done ? (
        <>
          <Notice tone="success">{t.confirmed}</Notice>
          <Link href="/" className={buttonClass}>
            {t.goToApp}
          </Link>
        </>
      ) : hasToken ? (
        <>
          <p className="text-sm text-muted">{t.intro}</p>
          {error && <Notice tone="error">{error}</Notice>}
          <button type="button" onClick={confirm} disabled={busy} className={buttonClass}>
            {busy ? t.confirming : t.confirm}
          </button>
        </>
      ) : (
        <Notice tone="error">{t.incomplete}</Notice>
      )}
    </div>
  );
}
