"use client";

import { useState } from "react";

import type { EditorEngine } from "@/editor/useEditorEngine";
import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";
import { useVersions } from "@/services/queries";
import type { DocumentVersion } from "@/types/document";

/**
 * One Undo and one Redo (E2, architecture §7). Two histories exist: the editor's own, fine-grained, for typing
 * since the last saved change was applied (a saved change is never part of it -- EditorState.apply), and the
 * server's, linear, over every saved step (typing merged in bursts, formatting, page setup, structure).
 * The rule is the same every time: Undo takes back typing first, step by step; when there is none left, it
 * takes back the last saved step, on the server, and says which. Redo mirrors it. Nothing is undone twice.
 */
export type Source = "typing" | "saved" | null;

export function undoSource(typingCan: boolean, savedCan: boolean): Source {
  return typingCan ? "typing" : savedCan ? "saved" : null;
}

/** The saved steps around the one the document shows: whether there is one before / after it, and the
 * description of the current one (what an undo would take back) and of the next (what a redo brings). */
export function savedSteps(versions: DocumentVersion[] | undefined) {
  if (!versions) return { canUndo: false, canRedo: false, current: null as DocumentVersion | null, next: null as DocumentVersion | null };
  const current = versions.find((version) => version.current) ?? null;
  if (!current) return { canUndo: false, canRedo: false, current: null, next: null };
  const older = versions.some((version) => version.number < current.number);
  const next = versions.filter((version) => version.number > current.number).sort((a, b) => a.number - b.number)[0] ?? null;
  return { canUndo: older, canRedo: next !== null, current, next };
}

export function useUnifiedHistory(engine: EditorEngine) {
  const { editor, document, history } = engine;
  useEditorForceUpdate(editor);
  const versions = useVersions(document.id, document.revision);
  const saved = savedSteps(versions.data);
  const [last, setLast] = useState<{ kind: "undone" | "redone"; what: string } | null>(null);

  const typingCanUndo = Boolean(editor && !editor.isDestroyed && editor.can().undo());
  const typingCanRedo = Boolean(editor && !editor.isDestroyed && editor.can().redo());
  const undoFrom = undoSource(typingCanUndo, saved.canUndo);
  const redoFrom = undoSource(typingCanRedo, saved.canRedo);

  async function undo() {
    setLast(null);
    if (undoFrom === "typing") editor!.chain().focus().undo().run();
    else if (undoFrom === "saved") {
      const what = saved.current?.description ?? "";
      await history.undo();
      setLast({ kind: "undone", what });
    }
  }

  async function redo() {
    setLast(null);
    if (redoFrom === "typing") editor!.chain().focus().redo().run();
    else if (redoFrom === "saved") {
      const what = saved.next?.description ?? "";
      await history.redo();
      setLast({ kind: "redone", what });
    }
  }

  return {
    canUndo: undoFrom !== null && !history.pending,
    canRedo: redoFrom !== null && !history.pending,
    undoFrom,
    redoFrom,
    undo,
    redo,
    pending: history.pending,
    error: history.error,
    /** The saved step last undone or redone, to say so ("Undone: Template applied"). */
    last,
    clearLast: () => setLast(null),
  };
}

export type UnifiedHistory = ReturnType<typeof useUnifiedHistory>;
