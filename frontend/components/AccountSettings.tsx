"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AppHeader } from "@/components/AppHeader";
import { inputClass } from "@/components/AuthForm";
import { changePassword } from "@/services/api";
import { useCurrentUser } from "@/services/queries";

const labelClass = "flex flex-col gap-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300";

/** Changing the password (ACCT-004): the current one first; every other browser is then signed out. */
export function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeated, setRepeated] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setDone(false);
    if (next !== repeated) {
      setError("The two new passwords aren't the same.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setRepeated("");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-labelledby="change-password-title"
      className="flex max-w-md flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
    >
      <h2 id="change-password-title" className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Change your password
      </h2>
      <label className={labelClass}>
        Current password
        <input type="password" required maxLength={256} autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className={inputClass} />
      </label>
      <div className="flex flex-col gap-1.5">
        <label className={labelClass}>
          New password
          <input
            type="password"
            required
            minLength={8}
            maxLength={256}
            autoComplete="new-password"
            aria-describedby="change-password-hint"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className={inputClass}
          />
        </label>
        <span id="change-password-hint" className="text-xs text-zinc-500">
          At least 8 characters. Every other browser signed in to your account is signed out.
        </span>
      </div>
      <label className={labelClass}>
        The new one again
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
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}
      {done && (
        <p role="status" className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
          Your password is changed. Every other browser that was signed in is signed out.
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="self-start rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {busy ? "Saving…" : "Change the password"}
      </button>
    </form>
  );
}

export function AccountSettings() {
  const { data: user, isPending } = useCurrentUser();

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Your account</h1>
        {isPending ? null : user ? (
          <>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Signed in as <span className="font-medium text-zinc-900 dark:text-zinc-50">{user.email}</span>
              {user.emailVerified ? " (confirmed)." : " (not confirmed yet)."}
            </p>
            <div className="mt-6">
              <ChangePasswordForm />
            </div>
          </>
        ) : (
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/login?next=%2Fsettings%2Faccount" className="font-medium text-accent hover:underline">
              Sign in
            </Link>{" "}
            to see your account.
          </p>
        )}
      </main>
    </div>
  );
}
