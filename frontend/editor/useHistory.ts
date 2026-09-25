"use client";

import { useState } from "react";

import type { Change } from "@/editor/EditorState";
import { errorMessage, redoFormatting, undoFormatting } from "@/services/api";

/** Undo and redo of saved changes (formatting, page setup, structure): the
 * backend's persisted version history, separate from the editor's own ↺/↻ for
 * typing. */
export function useHistory(change: Change) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: typeof undoFormatting, fallback: string) {
    setPending(true);
    setError(null);
    try {
      await change(action);
    } catch (err) {
      setError(errorMessage(err, fallback));
    } finally {
      setPending(false);
    }
  }

  return {
    undo: () => run(undoFormatting, "Nothing to undo."),
    redo: () => run(redoFormatting, "Nothing to redo."),
    pending,
    error,
  };
}

export type History = ReturnType<typeof useHistory>;
