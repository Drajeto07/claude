"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { buttonClasses } from "@/components/ui/Button";
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
      className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100"
    >
      <p>
        {sent ?? (
          <>
            {m.verify.promptStart} <strong className="font-medium">{email}</strong>
            {m.verify.promptEnd}
          </>
        )}
        {error && <span className="ml-1 text-red-700 dark:text-red-300">{error}</span>}
      </p>
      {!sent && (
        <button
          type="button"
          onClick={sendAgain}
          disabled={busy}
          className="shrink-0 rounded-full bg-amber-700 px-3 py-1 text-xs font-medium text-white hover:bg-amber-800 disabled:opacity-60"
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cardClass}>
      <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{done ? "Address confirmed" : "Confirm your address"}</h1>
      {done ? (
        <>
          <p role="status" className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
            Your address is confirmed.
          </p>
          <Link href="/" className={buttonClass}>
            Go to SmartDoc
          </Link>
        </>
      ) : hasToken ? (
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Confirm that the address this link was sent to is yours.</p>
          {error && (
            <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
              {error}
            </p>
          )}
          <button type="button" onClick={confirm} disabled={busy} className={buttonClass}>
            {busy ? "Confirming…" : "Confirm my address"}
          </button>
        </>
      ) : (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          This link is incomplete. Open the link from the e-mail again, or sign in and ask for a new one.
        </p>
      )}
    </div>
  );
}
