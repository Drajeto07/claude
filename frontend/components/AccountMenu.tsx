"use client";

import Link from "next/link";
import { LogOut } from "lucide-react";

import { logout } from "@/services/api";
import { useCurrentUser } from "@/services/queries";

export function AccountMenu() {
  const { data: user, isPending, isError } = useCurrentUser();

  if (isPending) return null;

  if (isError || user === null) {
    return (
      <Link
        href="/login"
        className="rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-300"
      >
        Sign in
      </Link>
    );
  }

  async function handleSignOut() {
    await logout();
    // A full page load on purpose: nothing of the signed-out user's documents may
    // survive in React state, the query cache or Next's client-side route cache.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login");
  }

  return (
    <div className="flex items-center gap-2">
      <span className="hidden max-w-[12rem] truncate text-xs text-zinc-500 sm:inline dark:text-zinc-400" title={user.email}>
        {user.fullName || user.email}
      </span>
      <button
        type="button"
        onClick={handleSignOut}
        aria-label="Sign out"
        title="Sign out"
        className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
      >
        <LogOut className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
