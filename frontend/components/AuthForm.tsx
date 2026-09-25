"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { login, register, safeNextPath } from "@/services/api";
import { queryKeys } from "@/services/queries";

type Mode = "login" | "register";

const COPY: Record<Mode, { title: string; submit: string; busy: string; switchPrompt: string; switchLink: string }> = {
  login: {
    title: "Sign in",
    submit: "Sign in",
    busy: "Signing in…",
    switchPrompt: "No account yet?",
    switchLink: "Create one",
  },
  register: {
    title: "Create your account",
    submit: "Create account",
    busy: "Creating account…",
    switchPrompt: "Already have an account?",
    switchLink: "Sign in",
  },
};

const inputClass =
  "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const next = safeNextPath(searchParams.get("next"));
  const copy = COPY[mode];

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    <form
      onSubmit={handleSubmit}
      className="flex w-full max-w-sm flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
    >
      <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{copy.title}</h1>

      {mode === "register" && (
        <label className="flex flex-col gap-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          <span>
            Name <span className="font-normal text-zinc-500">(optional)</span>
          </span>
          <input
            type="text"
            autoComplete="name"
            maxLength={255}
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className={inputClass}
          />
        </label>
      )}

      <label className="flex flex-col gap-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Email
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={inputClass}
        />
      </label>

      <label className="flex flex-col gap-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Password
        <input
          type="password"
          required
          minLength={mode === "register" ? 8 : 1}
          maxLength={256}
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputClass}
        />
        {mode === "register" && <span className="text-xs font-normal text-zinc-500">At least 8 characters.</span>}
      </label>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {busy ? copy.busy : copy.submit}
      </button>

      <p className="text-center text-sm text-zinc-500 dark:text-zinc-400">
        {copy.switchPrompt}{" "}
        <Link href={otherHref} className="font-medium text-accent hover:underline">
          {copy.switchLink}
        </Link>
      </p>
    </form>
  );
}
