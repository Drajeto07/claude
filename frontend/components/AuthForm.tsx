"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses, TextField } from "@/components/ui/TextField";
import { login, register, safeNextPath } from "@/services/api";
import { queryKeys, useEmailDelivery } from "@/services/queries";

type Mode = "login" | "register";

const COPY: Record<Mode, { title: string; subtitle: string; submit: string; busy: string; switchPrompt: string; switchLink: string }> = {
  login: {
    title: "Sign in",
    subtitle: "Pick up where you left off.",
    submit: "Sign in",
    busy: "Signing in…",
    switchPrompt: "No account yet?",
    switchLink: "Create one",
  },
  register: {
    title: "Create your account",
    subtitle: "Start with a document, a design or a template.",
    submit: "Create account",
    busy: "Creating account…",
    switchPrompt: "Already have an account?",
    switchLink: "Sign in",
  },
};

/** The input look, for forms that lay out their own labels (PasswordResetForms). */
export const inputClass = fieldClasses;

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const next = safeNextPath(searchParams.get("next"));
  // Where deleting an account (ACCT-005) lands.
  const accountDeleted = searchParams.get("deleted") === "1";
  const copy = COPY[mode];

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
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
          Your account is deleted, with everything in it.{emailDelivers === true && <> We&apos;ve sent a last e-mail to say so.</>}
        </Notice>
      )}

      {mode === "register" && (
        <TextField
          label="Name"
          labelNote="(optional)"
          type="text"
          autoComplete="name"
          maxLength={255}
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
      )}

      <TextField label="Email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />

      <div className="flex flex-col gap-1.5">
        <TextField
          label="Password"
          type="password"
          required
          minLength={mode === "register" ? 8 : 1}
          maxLength={256}
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={mode === "register" ? "At least 8 characters." : undefined}
        />
        {mode === "login" && (
          <Link href="/forgot-password" className="self-end rounded text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            Forgot your password?
          </Link>
        )}
      </div>

      {error && <Notice tone="error">{error}</Notice>}

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
