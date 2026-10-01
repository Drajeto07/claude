"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AppHeader } from "@/components/AppHeader";
import { inputClass } from "@/components/AuthForm";
import { changePassword, deleteAccount, signOutOtherSessions, signOutSession } from "@/services/api";
import { queryKeys, useCurrentUser, useSessions } from "@/services/queries";

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

const cardClass =
  "flex max-w-md flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900";

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** The browsers signed in to the account (ACCT-006): each can be signed out, or every one but this. */
export function SessionsList() {
  const queryClient = useQueryClient();
  const { data: sessions, isPending, error: loadError } = useSessions();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const others = sessions?.filter((session) => !session.current) ?? [];

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="sessions-title" className={cardClass}>
      <h2 id="sessions-title" className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Where you&apos;re signed in
      </h2>
      {isPending ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : loadError ? (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {loadError.message}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-zinc-200 dark:divide-zinc-800">
          {sessions?.map((session) => (
            <li key={session.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <div className="flex flex-col">
                <span className="font-medium text-zinc-900 dark:text-zinc-50">
                  {session.browser}
                  {session.current && <span className="ml-2 text-xs font-normal text-emerald-700 dark:text-emerald-300">This browser</span>}
                </span>
                <span className="text-xs text-zinc-500">
                  Signed in {when(session.createdAt)}
                  {session.lastUsedAt && ` · last used ${when(session.lastUsedAt)}`}
                </span>
              </div>
              {!session.current && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(() => signOutSession(session.id))}
                  aria-label={`Sign out ${session.browser}`}
                  className="shrink-0 rounded-full border border-zinc-300 px-3 py-1 text-xs font-medium text-zinc-700 hover:border-accent hover:text-accent disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-300"
                >
                  Sign out
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}
      {others.length > 0 && (
        <button
          type="button"
          disabled={busy}
          onClick={() => run(signOutOtherSessions)}
          className="self-start rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:border-accent hover:text-accent disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-300"
        >
          Sign out every other browser
        </button>
      )}
    </section>
  );
}

export const DELETE_CONFIRMATION = "delete my account";

/** Deleting the account (ACCT-005): says what goes, then the password and a typed confirmation. */
export function DeleteAccountForm() {
  const [password, setPassword] = useState("");
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const confirmed = typed.trim().toLowerCase() === DELETE_CONFIRMATION;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      // A full page load on purpose, as when signing out: nothing of the account may stay in memory.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?deleted=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-labelledby="delete-account-title" className={`${cardClass} border-red-200 dark:border-red-900/60`}>
      <h2 id="delete-account-title" className="text-base font-semibold text-red-700 dark:text-red-300">
        Delete the account
      </h2>
      <div className="text-sm text-zinc-700 dark:text-zinc-300">
        <p>This deletes, for good and at once:</p>
        <ul className="mt-1 list-disc pl-5">
          <li>your documents, their versions, pictures and kept originals;</li>
          <li>your templates and exports;</li>
          <li>your sign-ins everywhere, and the account itself.</li>
        </ul>
        <p className="mt-2">
          A paid plan must be cancelled first, in{" "}
          <Link href="/settings/billing" className="font-medium text-accent hover:underline">
            Plan and billing
          </Link>
          . It can&apos;t be undone.
        </p>
      </div>
      <label className={labelClass}>
        Your password
        <input type="password" required maxLength={256} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
      </label>
      <label className={labelClass}>
        <span>
          Type <span className="font-mono font-semibold">{DELETE_CONFIRMATION}</span> to confirm
        </span>
        <input type="text" required autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} className={inputClass} />
      </label>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || !confirmed}
        className="self-start rounded-full bg-red-600 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {busy ? "Deleting…" : "Delete my account"}
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
            <div className="mt-6 flex flex-col gap-6">
              <ChangePasswordForm />
              <SessionsList />
              <DeleteAccountForm />
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
