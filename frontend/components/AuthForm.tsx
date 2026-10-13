"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses, TextField } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import type { Messages } from "@/i18n/messages/en";
import { ApiError, login, NetworkError, register, safeNextPath } from "@/services/api";
import { queryKeys, useEmailDelivery } from "@/services/queries";

type Mode = "login" | "register";

/** The input look, for forms that lay out their own labels (PasswordResetForms). */
export const inputClass = fieldClasses;

/** What to tell the person, in the interface language: the API's own messages are English. */
export function authErrorMessage(error: unknown, mode: Mode, m: Messages): string {
  const errors = m.auth.errors;
  if (error instanceof NetworkError) return errors.offline;
  if (error instanceof ApiError) {
    if (error.status === 401) return errors.invalidCredentials;
    if (error.status === 409 && mode === "register") return errors.emailTaken;
    if (error.status === 422) return errors.invalidInput;
    if (error.status === 429) return errors.tooMany;
  }
  return errors.generic;
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { m } = useI18n();
  const next = safeNextPath(searchParams.get("next"));
  // Where deleting an account (ACCT-005) lands.
  const accountDeleted = searchParams.get("deleted") === "1";
  const copy = mode === "login" ? m.auth.login : m.auth.register;

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const { data: emailDelivers } = useEmailDelivery();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = mode === "login" ? await login(email, password) : await register(email, password, fullName);
      // Nothing cached before signing in may carry over to this account (the sign-in
      // page itself cached "nobody is signed in"), and the header knows at once who is.
      queryClient.clear();
      queryClient.setQueryData(queryKeys.currentUser, user);
      router.replace(next);
      router.refresh();
    } catch (err) {
      setError(err ?? new Error());
      setBusy(false);
    }
  }

  const otherHref = `${mode === "login" ? "/register" : "/login"}${next === "/" ? "" : `?next=${encodeURIComponent(next)}`}`;

  return (
    <form onSubmit={handleSubmit} className="flex w-full max-w-md flex-col gap-5 rounded-2xl border border-line bg-surface p-7 shadow-card sm:p-9">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{copy.title}</h1>
        <p className="mt-1.5 text-sm text-muted">{copy.subtitle}</p>
      </div>

      {mode === "login" && accountDeleted && (
        <Notice tone="success">
          {m.auth.login.accountDeleted}
          {emailDelivers === true && <> {m.auth.login.accountDeletedMail}</>}
        </Notice>
      )}

      {mode === "register" && (
        <TextField
          label={m.auth.fields.name}
          labelNote={m.auth.fields.optional}
          type="text"
          autoComplete="name"
          maxLength={255}
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
      )}

      <TextField label={m.auth.fields.email} type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />

      <div className="flex flex-col gap-1.5">
        <TextField
          label={m.auth.fields.password}
          type="password"
          required
          minLength={mode === "register" ? 8 : 1}
          maxLength={256}
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={mode === "register" ? m.auth.register.passwordHint : undefined}
        />
        {mode === "login" && (
          <Link href="/forgot-password" className="self-end rounded text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            {m.auth.login.forgot}
          </Link>
        )}
      </div>

      {error !== null && <Notice tone="error">{authErrorMessage(error, mode, m)}</Notice>}

      <Button type="submit" size="lg" block loading={busy} loadingLabel={copy.busy}>
        {copy.submit}
      </Button>

      <p className="text-center text-sm text-muted">
        {copy.switchPrompt}{" "}
        <Link href={otherHref} className="rounded font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {copy.switchLink}
        </Link>
      </p>
    </form>
  );
}
