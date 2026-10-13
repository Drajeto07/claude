"use client";

import { CreditCard, FolderOpen, Home, Languages, LayoutTemplate, LogOut, Menu, Plus, Settings, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { buttonClasses } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";
import { useI18n } from "@/i18n/I18nProvider";
import type { Messages } from "@/i18n/messages/en";
import { logout } from "@/services/api";
import { useCurrentUser } from "@/services/queries";

/**
 * The signed-in frame of SmartDoc 2.0 (docs/SMARTDOC_2_0_SPEC.md §4, S2-013, UI review
 * 2026-10-14): a light sidebar -- Create project, the main places (Translate among them),
 * settings, who is signed in, the theme switch -- and the same in a drawer under a slim top bar
 * on phones. Pages put their own <main> inside. The editor keeps its own full-screen layout.
 */
type ShellLabel = keyof Messages["shell"];
type Place = { href: string; label: ShellLabel; icon: typeof Home };

const PLACES: Place[] = [
  { href: "/", label: "home", icon: Home },
  { href: "/documents", label: "projects", icon: FolderOpen },
  { href: "/templates", label: "templates", icon: LayoutTemplate },
  { href: "/translate", label: "translate", icon: Languages },
];
const SETTINGS: Place[] = [
  { href: "/settings/account", label: "account", icon: Settings },
  { href: "/settings/billing", label: "billing", icon: CreditCard },
];

function isCurrent(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, icon: Icon, onNavigate }: Place & { onNavigate?: () => void }) {
  const pathname = usePathname() ?? "/";
  const { m } = useI18n();
  const current = isCurrent(pathname, href);
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={current ? "page" : undefined}
      className={`relative flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        current ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-muted hover:text-foreground"
      }`}
    >
      {current && <span aria-hidden="true" className="absolute -left-4 top-2 bottom-2 w-1 rounded-r-full bg-accent" />}
      <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={current ? 2.25 : 1.75} aria-hidden="true" />
      {m.shell[label]}
    </Link>
  );
}

function Account() {
  const { data: user } = useCurrentUser();
  const { m } = useI18n();
  if (!user) return null;

  async function signOut() {
    await logout();
    // A full page load: nothing of this account may survive in React state or caches.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login");
  }

  const name = user.fullName || user.email;
  return (
    <div className="flex items-center gap-2 rounded-2xl bg-surface-muted p-2">
      <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent">
        {name.trim().charAt(0).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground" title={user.email}>
          {name}
        </span>
        {user.fullName && <span className="block truncate text-xs text-muted">{user.email}</span>}
      </span>
      <ThemeSwitcher compact />
      <button
        type="button"
        onClick={signOut}
        aria-label={m.shell.signOut}
        title={m.shell.signOut}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <LogOut className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { m } = useI18n();
  return (
    <div className="flex h-full flex-col gap-6 px-4 py-5">
      <Link href="/" onClick={onNavigate} className="w-fit rounded-xl px-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <Logo />
      </Link>
      <Link href="/projects/new" onClick={onNavigate} className={buttonClasses({ block: true })}>
        <Plus className="h-4 w-4" aria-hidden="true" />
        {m.shell.createProject}
      </Link>
      <nav aria-label={m.shell.mainNav} className="flex flex-col gap-0.5">
        {PLACES.map((place) => (
          <NavLink key={place.href} {...place} onNavigate={onNavigate} />
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-3">
        <nav aria-label={m.shell.settingsNav} className="flex flex-col gap-0.5 border-t border-line pt-3">
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
  const { m } = useI18n();

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="flex min-h-full flex-1 bg-background">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-line bg-surface md:block">
        <Sidebar />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label={m.shell.menu}>
          <button type="button" aria-label={m.shell.closeMenu} className="absolute inset-0 bg-slate-900/30" onClick={() => setOpen(false)} tabIndex={-1} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] border-r border-line bg-surface shadow-pop">
            <button
              ref={closeRef}
              type="button"
              onClick={() => setOpen(false)}
              aria-label={m.shell.closeMenu}
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
            aria-label={m.shell.openMenu}
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
