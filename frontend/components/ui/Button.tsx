import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * The SmartDoc 2.0 button (docs/SMARTDOC_2_0_SPEC.md §4). One look per job:
 * primary -- the screen's main action (blue-to-purple); secondary -- an alternative;
 * ghost -- a quiet action in toolbars and lists; danger -- deleting or leaving for good.
 * While `loading`, it stays the same size, shows a spinner and its busy label, and can't
 * be pressed again.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-r from-brand-blue to-brand-purple text-white shadow-sm hover:brightness-110 active:brightness-95",
  secondary:
    "border border-line bg-surface text-foreground hover:bg-surface-muted",
  ghost: "text-foreground hover:bg-surface-muted",
  danger: "bg-danger text-white shadow-sm hover:brightness-110",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-lg px-3 text-xs",
  md: "h-10 gap-2 rounded-xl px-4 text-sm",
  lg: "h-12 gap-2 rounded-xl px-5 text-base",
};

export function buttonClasses({ variant = "primary", size = "md", block = false }: { variant?: ButtonVariant; size?: ButtonSize; block?: boolean } = {}) {
  return [
    "inline-flex items-center justify-center font-medium transition-[filter,background-color,box-shadow]",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    "disabled:cursor-not-allowed disabled:opacity-60",
    VARIANTS[variant],
    SIZES[size],
    block ? "w-full" : "",
  ].join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Fills its container's width. */
  block?: boolean;
  loading?: boolean;
  /** What the button says while loading (e.g. "Signing in…"); its children otherwise. */
  loadingLabel?: ReactNode;
};

export function Button({ variant, size, block, loading = false, loadingLabel, disabled, className = "", children, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`${buttonClasses({ variant, size, block })} ${className}`}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
      {loading && loadingLabel ? loadingLabel : children}
    </button>
  );
}
