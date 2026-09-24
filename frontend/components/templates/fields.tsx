"use client";

import { X } from "lucide-react";
import { useId, type ReactNode } from "react";

/**
 * Inputs for style-system fields. Every one of them can be "not set" (null):
 * the template then leaves that property to the document-wide value or the
 * engine's default, which is different from, say, explicitly "not bold".
 */

const inputClass =
  "w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50 disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-500 dark:disabled:bg-zinc-900 dark:disabled:text-zinc-400";

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
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
  const id = useId();
  return (
    <Field id={id} label={label}>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        className={inputClass}
        value={value ?? ""}
        placeholder="Not set"
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
  const id = useId();
  const listId = `${id}-suggestions`;
  return (
    <Field id={id} label={label}>
      <input
        id={id}
        type="text"
        className={inputClass}
        value={value ?? ""}
        placeholder="Not set"
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
  const id = useId();
  return (
    <Field id={id} label={label}>
      <select
        id={id}
        className={inputClass}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value === "" ? null : (event.target.value as T))}
      >
        <option value="">Not set</option>
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
export function ToggleField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | null | undefined;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <SelectField
      label={label}
      value={value == null ? null : value ? "on" : "off"}
      onChange={(choice) => onChange(choice === null ? null : choice === "on")}
      options={[
        { value: "on", label: "On" },
        { value: "off", label: "Off" },
      ]}
    />
  );
}

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (value: string | null) => void;
}) {
  const id = useId();
  return (
    <Field id={id} label={label}>
      <div className="flex items-center gap-1.5">
        <input
          type="color"
          aria-label={`${label}: pick`}
          className="h-8 w-9 shrink-0 cursor-pointer rounded border border-zinc-300 bg-white p-0.5 dark:border-zinc-700 dark:bg-zinc-950"
          value={value && HEX_COLOR.test(value) ? value : "#000000"}
          onChange={(event) => onChange(event.target.value)}
        />
        <input
          id={id}
          type="text"
          className={inputClass}
          value={value ?? ""}
          placeholder="Not set"
          maxLength={7}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange(null)}
            aria-label={`${label}: clear`}
            title="Clear"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>
    </Field>
  );
}
