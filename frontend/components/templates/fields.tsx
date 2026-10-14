"use client";

import { X } from "lucide-react";
import { useId, type ReactNode } from "react";

import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";

/**
 * Inputs for style-system fields. Every one of them can be "not set" (null):
 * the template then leaves that property to the document-wide value or the
 * engine's default, which is different from, say, explicitly "not bold".
 */

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-surface px-2 text-sm text-foreground placeholder:text-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-muted";

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 0.5,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  const { m } = useI18n();
  const id = useId();
  return (
    <Field id={id} label={label}>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        className={inputClass}
        value={value ?? ""}
        placeholder={m.styleForm.notSet}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const raw = event.target.value;
          const parsed = raw === "" ? null : Number(raw);
          onChange(parsed === null || Number.isNaN(parsed) ? null : parsed);
        }}
      />
    </Field>
  );
}

export function TextField({
  label,
  value,
  onChange,
  suggestions,
  maxLength,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (value: string | null) => void;
  suggestions?: readonly string[];
  maxLength?: number;
}) {
  const { m } = useI18n();
  const id = useId();
  const listId = `${id}-suggestions`;
  return (
    <Field id={id} label={label}>
      <input
        id={id}
        type="text"
        className={inputClass}
        value={value ?? ""}
        placeholder={m.styleForm.notSet}
        maxLength={maxLength}
        list={suggestions ? listId : undefined}
        onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
      />
      {suggestions && (
        <datalist id={listId}>
          {suggestions.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
      )}
    </Field>
  );
}

export function SelectField<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T | null | undefined;
  onChange: (value: T | null) => void;
  options: readonly { value: T; label: string }[];
}) {
  const { m } = useI18n();
  const id = useId();
  return (
    <Field id={id} label={label}>
      <select id={id} className={inputClass} value={value ?? ""} onChange={(event) => onChange(event.target.value === "" ? null : (event.target.value as T))}>
        <option value="">{m.styleForm.notSet}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

/** On / Off / Not set -- "Off" really turns it off, "Not set" leaves it alone. */
export function ToggleField({ label, value, onChange }: { label: string; value: boolean | null | undefined; onChange: (value: boolean | null) => void }) {
  const { m } = useI18n();
  return (
    <SelectField
      label={label}
      value={value == null ? null : value ? "on" : "off"}
      onChange={(choice) => onChange(choice === null ? null : choice === "on")}
      options={[
        { value: "on", label: m.styleForm.on },
        { value: "off", label: m.styleForm.off },
      ]}
    />
  );
}

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export function ColorField({ label, value, onChange }: { label: string; value: string | null | undefined; onChange: (value: string | null) => void }) {
  const { m } = useI18n();
  const id = useId();
  return (
    <Field id={id} label={label}>
      <div className="flex items-center gap-1.5">
        <input
          type="color"
          aria-label={format(m.styleForm.pick, { label })}
          className="h-9 w-9 shrink-0 cursor-pointer rounded-lg border border-line bg-surface p-0.5"
          value={value && HEX_COLOR.test(value) ? value : "#000000"}
          onChange={(event) => onChange(event.target.value)}
        />
        <input
          id={id}
          type="text"
          className={inputClass}
          value={value ?? ""}
          placeholder={m.styleForm.notSet}
          maxLength={7}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange(null)}
            aria-label={format(m.styleForm.clear, { label })}
            title={m.styleForm.clearTitle}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-surface-muted hover:text-foreground"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>
    </Field>
  );
}
