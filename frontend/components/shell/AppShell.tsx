"use client";

import { CreditCard, FolderOpen, Home, LayoutTemplate, LogOut, Menu, Plus, Settings, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { buttonClasses } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { logout } from "@/services/api";
import { useCurrentUser } from "@/services/queries";

/**
 * The signed-in frame of SmartDoc 2.0 (docs/SMARTDOC_2_0_SPEC.md §4, S2-013): a left sidebar
 * on wide screens -- Create project, the main places, settings, who is signed in -- and the
 * same in a drawer under a slim top bar on phones. Pages put their own <main> inside.
 * The editor keeps its own full-screen layout.
 */
const PLACES = [
  { href: "/", label: "Home", icon: Home },
  { href: "/documents", label: "Projects", icon: FolderOpen },
  { href: "/templates", label: "Templates", icon: LayoutTemplate },
];
const SETTINGS = [
  { href: "/settings/account", label: "Your account", icon: Settings },
  { href: "/settings/billing", label: "Plan and billing", icon: CreditCard },
];

function isCurrent(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, icon: Icon, onNavigate }: { href: string; label: string; icon: typeof Home; onNavigate?: () => void }) {
  const pathname = usePathname() ?? "/";
  const current = isCurrent(pathname, href);
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={current ? "page" : undefined}
      className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        current ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface-muted hover:text-foreground"
      }`}
    >
      <Icon className="h-4.5 w-4.5 shrink-0" aria-hidden="true" />
      {label}
    </Link>
  );
}

function Account() {
  const { data: user } = useCurrentUser();
  if (!user) return null;

  async function signOut() {
    await logout();
    // A full page load: nothing of this account may survive in React state or caches.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login");
  }

  const name = user.fullName || user.email;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-muted/60 p-2.5">
      <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-blue to-brand-purple text-sm font-semibold text-white">
        {name.trim().charAt(0).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground" title={user.email}>
          {name}
        </span>
        {user.fullName && <span className="block truncate text-xs text-muted">{user.email}</span>}
      </span>
      <button
        type="button"
        onClick={signOut}
        aria-label="Sign out"
        title="Sign out"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <LogOut className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-6 px-3 py-5">
      <Link href="/" onClick={onNavigate} className="w-fit rounded-xl px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <Logo />
      </Link>
      <Link href="/new" onClick={onNavigate} className={buttonClasses({ block: true })}>
        <Plus className="h-4 w-4" aria-hidden="true" />
        Create project
      </Link>
      <nav aria-label="Main" className="flex flex-col gap-1">
        {PLACES.map((place) => (
          <NavLink key={place.href} {...place} onNavigate={onNavigate} />
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-4">
        <nav aria-label="Settings" className="flex flex-col gap-1">
          {SETTINGS.map((place) => (
            <NavLink key={place.href} {...place} onNavigate={onNavigate} />
          ))}
        </nav>
        <Account />
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="flex min-h-full flex-1 bg-surface-muted">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-line bg-surface md:block">
        <Sidebar />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" aria-label="Close the menu" className="absolute inset-0 bg-slate-900/30" onClick={() => setOpen(false)} tabIndex={-1} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] border-r border-line bg-surface shadow-pop">
            <button
              ref={closeRef}
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close the menu"
              className="absolute right-3 top-4 flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-line bg-surface px-4 md:hidden">
          <Link href="/" className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <Logo />
          </Link>
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label="Open the menu"
            aria-expanded={open}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-foreground hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
