"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { AppShell } from "@/components/shell/AppShell";
import { inputClass } from "@/components/AuthForm";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { formatDateTime } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { changePassword, deleteAccount, signOutOtherSessions, signOutSession } from "@/services/api";
import { queryKeys, useCurrentUser, useSessions } from "@/services/queries";

const labelClass = "flex flex-col gap-1.5 text-sm font-medium text-foreground";
const cardClass = "flex max-w-md flex-col gap-4 rounded-2xl border border-line bg-surface p-6 shadow-card";
const quietButton = "rounded-full border border-line-strong font-medium text-foreground transition-colors hover:border-accent hover:text-accent disabled:opacity-60";

/** Changing the password (ACCT-004): the current one first; every other browser is then signed out. */
export function ChangePasswordForm() {
  const { m } = useI18n();
  const t = m.account.password;
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
      setError(t.mismatch);
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
      setError(err instanceof Error ? err.message : m.account.somethingWrong);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-labelledby="change-password-title" className={cardClass}>
      <h2 id="change-password-title" className="text-base font-semibold text-foreground">
        {t.title}
      </h2>
      <label className={labelClass}>
        {t.current}
        <input type="password" required maxLength={256} autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className={inputClass} />
      </label>
      <div className="flex flex-col gap-1.5">
        <label className={labelClass}>
          {t.next}
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
        <span id="change-password-hint" className="text-xs text-muted">
          {t.hint}
        </span>
      </div>
      <label className={labelClass}>
        {t.repeat}
        <input type="password" required minLength={8} maxLength={256} autoComplete="new-password" value={repeated} onChange={(e) => setRepeated(e.target.value)} className={inputClass} />
      </label>
      {error && <Notice tone="error">{error}</Notice>}
      {done && <Notice tone="success">{t.done}</Notice>}
      <Button type="submit" loading={busy} loadingLabel={t.saving} className="self-start">
        {t.submit}
      </Button>
    </form>
  );
}

/** The browsers signed in to the account (ACCT-006): each can be signed out, or every one but this. */
export function SessionsList() {
  const { m, locale } = useI18n();
  const t = m.account.sessions;
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
      setError(err instanceof Error ? err.message : m.account.somethingWrong);
    } finally {
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="sessions-title" className={cardClass}>
      <h2 id="sessions-title" className="text-base font-semibold text-foreground">
        {t.title}
      </h2>
      {isPending ? (
        <p className="text-sm text-muted">{m.common.loading}</p>
      ) : loadError ? (
        <Notice tone="error">{loadError.message}</Notice>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {sessions?.map((session) => (
            <li key={session.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <div className="flex flex-col">
                <span className="font-medium text-foreground">
                  {session.browser}
                  {session.current && <span className="ml-2 text-xs font-normal text-success">{t.thisBrowser}</span>}
                </span>
                <span className="text-xs text-muted">
                  {format(t.signedIn, { when: formatDateTime(session.createdAt, locale) })}
                  {session.lastUsedAt && format(t.lastUsed, { when: formatDateTime(session.lastUsedAt, locale) })}
                </span>
              </div>
              {!session.current && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(() => signOutSession(session.id))}
                  aria-label={format(t.signOutNamed, { browser: session.browser })}
                  className={`${quietButton} shrink-0 px-3 py-1 text-xs`}
                >
                  {t.signOut}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {others.length > 0 && (
        <button type="button" disabled={busy} onClick={() => run(signOutOtherSessions)} className={`${quietButton} self-start px-4 py-2 text-sm`}>
          {t.signOutOthers}
        </button>
      )}
    </section>
  );
}

/** Deleting the account (ACCT-005): says what goes, then the password and a typed confirmation
 * (the phrase in the interface language). */
export function DeleteAccountForm() {
  const { m } = useI18n();
  const t = m.account.delete;
  const [password, setPassword] = useState("");
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const confirmed = typed.trim().toLowerCase() === t.phrase;
  const [beforeLink, afterLink] = t.paidFirst.split("{link}");

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
      setError(err instanceof Error ? err.message : m.account.somethingWrong);
      setBusy(false);
    }
  }

  const [beforePhrase, afterPhrase] = t.typeToConfirm.split("{phrase}");
  return (
    <form onSubmit={handleSubmit} aria-labelledby="delete-account-title" className={`${cardClass} border-danger/30`}>
      <h2 id="delete-account-title" className="text-base font-semibold text-danger">
        {t.title}
      </h2>
      <div className="text-sm text-foreground">
        <p>{t.intro}</p>
        <ul className="mt-1 list-disc pl-5">
          {t.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="mt-2">
          {beforeLink}
          <Link href="/settings/billing" className="font-medium text-accent hover:underline">
            {t.billingLink}
          </Link>
          {afterLink}
        </p>
      </div>
      <label className={labelClass}>
        {t.password}
        <input type="password" required maxLength={256} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
      </label>
      <label className={labelClass}>
        <span>
          {beforePhrase}
          <span className="font-mono font-semibold">{t.phrase}</span>
          {afterPhrase}
        </span>
        <input type="text" required autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} className={inputClass} />
      </label>
      {error && <Notice tone="error">{error}</Notice>}
      <Button type="submit" variant="danger" disabled={!confirmed} loading={busy} loadingLabel={t.deleting} className="self-start">
        {t.submit}
      </Button>
    </form>
  );
}

export function AccountSettings() {
  const { m } = useI18n();
  const t = m.account;
  const { data: user, isPending } = useCurrentUser();
  const [beforeEmail, afterEmail] = t.signedInAs.split("{email}");

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{t.title}</h1>
        {isPending ? null : user ? (
          <>
            <p className="mt-1 text-sm text-muted">
              {beforeEmail}
              <span className="font-medium text-foreground">{user.email}</span>
              {afterEmail} {user.emailVerified ? t.confirmed : t.notConfirmed}
            </p>
            <div className="mt-6 flex flex-col gap-6">
              {/* The interface language (D-010) and the theme: both remembered on this browser, neither touches a document. */}
              <section className="grid gap-6 rounded-2xl border border-line bg-surface p-5 shadow-card md:grid-cols-2">
                <LanguageSwitcher />
                <ThemeSwitcher />
              </section>
              <div className="grid items-start gap-6 lg:grid-cols-2">
                <ChangePasswordForm />
                <SessionsList />
              </div>
              <DeleteAccountForm />
            </div>
          </>
        ) : (
          <p className="mt-2 text-sm text-muted">
            <Link href="/login?next=%2Fsettings%2Faccount" className="font-medium text-accent hover:underline">
              {t.signIn}
            </Link>{" "}
            — {t.signInToSee}
          </p>
        )}
      </main>
    </AppShell>
  );
}
