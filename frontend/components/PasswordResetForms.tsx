"use client";

import Link from "next/link";
import { useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";

import { inputClass } from "@/components/AuthForm";
import { confirmPasswordReset, requestPasswordReset } from "@/services/api";

/**
 * Password reset (ACCT-002): asking for a link, and choosing a new password with it.
 * The link carries its token in the fragment (#token=...), which no browser sends to
 * a server; it is read when the form is sent, and taken out of the address bar once
 * it has been used.
 */

const cardClass =
  "flex w-full max-w-sm flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900";
const buttonClass =
  "rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:opacity-60";
const labelClass = "flex flex-col gap-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300";

function Problem({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
      {children}
    </p>
  );
}

function Done({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
      {children}
    </p>
  );
}

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSent(await requestPasswordReset(email));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className={cardClass}>
      <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Forgot your password?</h1>
      {sent ? (
        <Done>{sent}</Done>
      ) : (
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Enter the address you signed up with, and we&apos;ll e-mail you a link to choose a new password.</p>
          <label className={labelClass}>
            Email
            <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
          </label>
          {error && <Problem>{error}</Problem>}
          <button type="submit" disabled={busy} className={buttonClass}>
            {busy ? "Sending…" : "Send the link"}
          </button>
        </>
      )}
      <p className="text-center text-sm text-zinc-500 dark:text-zinc-400">
        <Link href="/login" className="font-medium text-accent hover:underline">
          Back to sign in
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
      setError("The two passwords aren't the same.");
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className={cardClass}>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Password changed</h1>
        <Done>Your password is changed, and every browser that was signed in to your account is signed out.</Done>
        <Link href="/login" className={`${buttonClass} text-center`}>
          Sign in with the new password
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={cardClass}>
      <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Choose a new password</h1>
      {hasToken ? (
        <>
          <div className="flex flex-col gap-1.5">
            <label className={labelClass}>
              New password
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
            <span id="new-password-hint" className="text-xs text-zinc-500">
              At least 8 characters.
            </span>
          </div>
          <label className={labelClass}>
            The same again
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
            {busy ? "Saving…" : "Save the new password"}
          </button>
        </>
      ) : (
        <Problem>This link is incomplete. Open the link from the e-mail again, or ask for a new one.</Problem>
      )}
      <p className="text-center text-sm text-zinc-500 dark:text-zinc-400">
        <Link href="/forgot-password" className="font-medium text-accent hover:underline">
          Ask for a new link
        </Link>
      </p>
    </form>
  );
}
