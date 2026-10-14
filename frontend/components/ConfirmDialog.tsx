"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { useI18n } from "@/i18n/I18nProvider";

/**
 * Asks before something that can't be undone. Focus starts on Cancel, Escape
 * cancels, and the confirm button waits (`busy`) while the action runs.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busy = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { m } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" className="w-full max-w-md rounded-2xl border border-line bg-surface p-5 shadow-pop">
        <h2 id="confirm-title" className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <AlertTriangle className="h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
          {title}
        </h2>
        <div className="mt-2 text-sm text-muted">{children}</div>
        {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-xl px-4 py-2 text-sm font-medium text-foreground hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          >
            {m.confirm.cancel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-xl bg-danger px-4 py-2 text-sm font-medium text-white hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger focus-visible:ring-offset-2 disabled:opacity-60"
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
