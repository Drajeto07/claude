"use client";

import Link from "next/link";
import { useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";

import { inputClass } from "@/components/AuthForm";
import { buttonClasses } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { useI18n } from "@/i18n/I18nProvider";
import { confirmPasswordReset, requestPasswordReset } from "@/services/api";
import { useEmailDelivery } from "@/services/queries";

/**
 * Password reset (ACCT-002): asking for a link, and choosing a new password with it.
 * The link carries its token in the fragment (#token=...), which no browser sends to
 * a server; it is read when the form is sent, and taken out of the address bar once
 * it has been used.
 */

const cardClass = "flex w-full max-w-md flex-col gap-5 rounded-2xl border border-line bg-surface p-7 shadow-card sm:p-9";
const buttonClass = buttonClasses({ size: "lg", block: true });
const labelClass = "flex flex-col gap-1.5 text-sm font-medium text-foreground";

function Problem({ children }: { children: ReactNode }) {
  return (
    <Notice tone="error">{children}</Notice>
  );
}

function Done({ children }: { children: ReactNode }) {
  return (
    <Notice tone="success">{children}</Notice>
  );
}

export function ForgotPasswordForm() {
  const { m } = useI18n();
  const t = m.passwordReset;
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // While this server sends no e-mail (RELEASE) no link could arrive, so none is offered.
  const { data: emailDelivers } = useEmailDelivery();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSent(await requestPasswordReset(email));
    } catch (err) {
      setError(err instanceof Error ? err.message : t.somethingWrong);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className={cardClass}>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{t.forgotTitle}</h1>
      {emailDelivers === false ? (
        <p role="status" className="rounded-xl border border-warning/30 bg-warning-soft px-3.5 py-2.5 text-sm text-foreground">
          {t.unavailable}
        </p>
      ) : sent ? (
        <Done>{sent}</Done>
      ) : (
        <>
          <p className="text-sm text-muted">{t.forgotIntro}</p>
          <label className={labelClass}>
            {t.email}
            <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
          </label>
          {error && <Problem>{error}</Problem>}
          <button type="submit" disabled={busy} className={buttonClass}>
            {busy ? t.sending : t.send}
          </button>
        </>
      )}
      <p className="text-center text-sm text-muted">
        <Link href="/login" className="font-medium text-accent hover:underline">
          {t.backToSignIn}
        </Link>
      </p>
    </form>
  );
}

const TOKEN = /(?:^#|&)token=([A-Za-z0-9_-]+)/;

function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** Whether the address holds a link's token; the server render assumes it does. */
function useLinkHasToken(): boolean {
  return useSyncExternalStore(
    subscribeToHash,
    () => TOKEN.test(window.location.hash),
    () => true,
  );
}

export function ResetPasswordForm() {
  const { m } = useI18n();
  const t = m.passwordReset;
  const hasToken = useLinkHasToken();
  const [password, setPassword] = useState("");
  const [repeated, setRepeated] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const token = TOKEN.exec(window.location.hash)?.[1];
    if (!token) return;
    if (password !== repeated) {
      setError(t.mismatch);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await confirmPasswordReset(token, password);
      // Used now: the token goes from the address bar (and so from a bookmark or a refresh).
      window.history.replaceState(null, "", window.location.pathname);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.somethingWrong);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className={cardClass}>
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{t.changedTitle}</h1>
        <Done>{t.changedText}</Done>
        <Link href="/login" className={`${buttonClass} text-center`}>
          {t.signInWithNew}
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={cardClass}>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">{t.chooseTitle}</h1>
      {hasToken ? (
        <>
          <div className="flex flex-col gap-1.5">
            <label className={labelClass}>
              {t.next}
              <input
                type="password"
                required
                minLength={8}
                maxLength={256}
                autoComplete="new-password"
                aria-describedby="new-password-hint"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputClass}
              />
            </label>
            <span id="new-password-hint" className="text-xs text-muted">
              {t.hint}
            </span>
          </div>
          <label className={labelClass}>
            {t.repeat}
            <input
              type="password"
              required
              minLength={8}
              maxLength={256}
              autoComplete="new-password"
              value={repeated}
              onChange={(e) => setRepeated(e.target.value)}
              className={inputClass}
            />
          </label>
          {error && <Problem>{error}</Problem>}
          <button type="submit" disabled={busy} className={buttonClass}>
            {busy ? t.saving : t.save}
          </button>
        </>
      ) : (
        <Problem>{t.incomplete}</Problem>
      )}
      <p className="text-center text-sm text-muted">
        <Link href="/forgot-password" className="font-medium text-accent hover:underline">
          {t.askNew}
        </Link>
      </p>
    </form>
  );
}
