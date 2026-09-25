"use client";

import type { Editor } from "@tiptap/react";
import { createContext, useCallback, useContext, type ReactNode, type RefObject } from "react";

import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { getSelectedElementId } from "@/editor/elementId";
import { selectElementById, type Selection } from "@/editor/useSelection";
import type { Document } from "@/types/document";

/** A change to the document: the server call that makes it, given the document's
 * id, answering with the new version. */
export type Change = (action: (documentId: string) => Promise<Document>) => Promise<Document>;

/**
 * How every change reaches the document. Typing not yet saved goes first, so a
 * change can never overwrite it (and a failed save stops the change); then the
 * change; then its result replaces what the editor shows, with the cursor kept
 * in the element it was in. `apply` is the last step alone, for a result that
 * came another way (a formatting job).
 */
export function useDocumentChanges(
  editor: Editor | null,
  documentRef: RefObject<Document>,
  setDocument: (document: Document) => void,
  flush: () => Promise<unknown>,
) {
  const apply = useCallback(
    (updated: Document) => {
      const selected = editor ? getSelectedElementId(editor) : null;
      setDocument(updated);
      if (editor && !editor.isDestroyed) {
        editor.commands.setContent(documentToTiptapJSON(updated), { emitUpdate: false });
        if (selected) selectElementById(editor, selected);
      }
    },
    [editor, setDocument],
  );

  const change = useCallback<Change>(
    async (action) => {
      await flush();
      const updated = await action(documentRef.current.id);
      apply(updated);
      return updated;
    },
    [flush, apply, documentRef],
  );

  return { apply, change };
}

/** What the editor's panels share: the document, the editor, what is selected,
 * and the way to change the document. */
export type EditorState = {
  document: Document;
  editor: Editor | null;
  selection: Selection;
  change: Change;
  flush: () => Promise<unknown>;
};

const EditorStateContext = createContext<EditorState | null>(null);

export function EditorStateProvider({ value, children }: { value: EditorState; children: ReactNode }) {
  return <EditorStateContext.Provider value={value}>{children}</EditorStateContext.Provider>;
}

export function useDocumentEditor(): EditorState {
  const state = useContext(EditorStateContext);
  if (!state) throw new Error("useDocumentEditor is used outside DocumentEditorShell");
  return state;
}
