"use client";

import { useState } from "react";

/** The document's title in the header: click to rename, Enter to keep, Escape to cancel. */
export function EditableTitle({ title, onRename }: { title: string; onRename: (title: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  function commit() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== title) onRename(trimmed);
    else setDraft(title);
  }

  if (editing) {
    return (
      <input
        autoFocus
        aria-label="Document title"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setDraft(title);
            setEditing(false);
          }
        }}
        className="max-w-[240px] rounded border border-accent bg-white px-1.5 py-0.5 text-sm font-medium text-zinc-900 focus:outline-none dark:bg-zinc-900 dark:text-zinc-50"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setDraft(title);
        setEditing(true);
      }}
      title="Rename document"
      className="group flex max-w-[240px] items-center gap-1.5 truncate text-sm font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
    >
      <span className="truncate">{title}</span>
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5 shrink-0 opacity-0 group-hover:opacity-100" aria-hidden="true">
        <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
      </svg>
    </button>
  );
}
