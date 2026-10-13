import type { ReactNode } from "react";

/**
 * A message inside a form or panel: `error` is announced at once (role="alert"), the others
 * politely (role="status").
 */
const TONES = {
  error: "border-danger/20 bg-danger/5 text-danger",
  success: "border-success/20 bg-success/5 text-success",
  info: "border-accent/20 bg-accent/5 text-foreground",
} as const;

export function Notice({ tone = "info", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return (
    <p role={tone === "error" ? "alert" : "status"} className={`rounded-xl border px-3.5 py-2.5 text-sm ${TONES[tone]}`}>
      {children}
    </p>
  );
}
