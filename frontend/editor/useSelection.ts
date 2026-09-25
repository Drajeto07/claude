"use client";

import type { Editor } from "@tiptap/react";

import { getSelectedElementId } from "@/editor/elementId";
import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";
import type { Document } from "@/types/document";

/** Which element the cursor is in, and the alignment its resolved style gives it.
 * Re-renders the caller on every selection change. */
export function useSelection(editor: Editor | null, document: Document) {
  useEditorForceUpdate(editor);
  const selectedElementId = editor ? getSelectedElementId(editor) : null;
  const selectedElement = selectedElementId ? (document.elements.find((element) => element.id === selectedElementId) ?? null) : null;
  const alignment = selectedElement?.styleRef ? (document.resolvedStyles[selectedElement.styleRef]?.["text-align"] ?? null) : null;
  return { selectedElementId, selectedElement, alignment };
}

export type Selection = ReturnType<typeof useSelection>;

/** Puts the cursor back in an element after the editor's content was replaced
 * (which resets the selection), so the panel editing it stays on it. */
export function selectElementById(editor: Editor, elementId: string) {
  let targetPos: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (targetPos !== null) return false;
    if (node.attrs?.elementId === elementId) {
      targetPos = pos;
      return false;
    }
    return true;
  });
  if (targetPos !== null) editor.commands.setTextSelection(targetPos + 1);
}
