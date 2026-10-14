"use client";

import Link from "next/link";
import { CreditCard, LogOut, UserRound } from "lucide-react";

import { useI18n } from "@/i18n/I18nProvider";
import { logout } from "@/services/api";
import { useCurrentUser } from "@/services/queries";

const iconButton =
  "flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

export function AccountMenu() {
  const { m } = useI18n();
  const { data: user, isPending, isError } = useCurrentUser();

  if (isPending) return null;

  if (isError || user === null) {
    return (
      <Link
        href="/login"
        className="rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-accent hover:text-accent"
      >
        {m.landing.signIn}
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
      <span className="hidden max-w-[12rem] truncate text-xs text-muted sm:inline" title={user.email}>
        {user.fullName || user.email}
      </span>
      <Link
        href="/settings/account"
        aria-label={m.shell.account}
        title={m.shell.account}
        className={iconButton}
      >
        <UserRound className="h-4 w-4" aria-hidden="true" />
      </Link>
      <Link
        href="/settings/billing"
        aria-label={m.shell.billing}
        title={m.shell.billing}
        className={iconButton}
      >
        <CreditCard className="h-4 w-4" aria-hidden="true" />
      </Link>
      <button
        type="button"
        onClick={handleSignOut}
        aria-label={m.shell.signOut}
        title={m.shell.signOut}
        className={iconButton}
      >
        <LogOut className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
