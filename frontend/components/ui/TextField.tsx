import { useId, type InputHTMLAttributes, type ReactNode } from "react";

/**
 * A labelled text input (docs/SMARTDOC_2_0_SPEC.md §4): the label names the field for
 * assistive technology and for tests (getByLabel), the hint and the error are tied to it
 * with aria-describedby, and an error marks it aria-invalid.
 */
type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  /** Shown after the label, quieter: "(optional)". */
  labelNote?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
};

export const fieldClasses =
  "h-11 w-full rounded-xl border border-line bg-surface px-3.5 text-sm text-foreground shadow-sm outline-none transition-[border-color,box-shadow] " +
  "placeholder:text-muted/70 focus:border-accent focus:ring-4 focus:ring-accent/15 aria-[invalid=true]:border-danger aria-[invalid=true]:focus:ring-danger/15";

export function TextField({ label, labelNote, hint, error, className = "", ...input }: TextFieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
        {labelNote && <span className="ml-1 font-normal text-muted">{labelNote}</span>}
      </label>
      <input id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} className={fieldClasses} {...input} />
      {hint && (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
