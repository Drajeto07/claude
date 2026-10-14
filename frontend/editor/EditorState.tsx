"use client";

import { EditorState as ProseMirrorState } from "@tiptap/pm/state";
import type { Editor } from "@tiptap/react";
import { createContext, useCallback, useContext, type ReactNode, type RefObject } from "react";

import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { getSelectedElementId } from "@/editor/elementId";
import { REPAGINATE } from "@/editor/pagination";
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
        // Not a typing step: kept out of the editor's own undo history, so Undo can never take back a saved
        // change locally (the change is undone on the server, where it was made -- useUnifiedHistory).
        editor.chain().setMeta("addToHistory", false).setContent(documentToTiptapJSON(updated), { emitUpdate: false }).run();
        resetTypingHistory(editor);
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

/**
 * A saved change starts a fresh typing history: the editor's own undo and redo never reach across it (a step
 * typed before it would be mapped onto content that has since been replaced -- counted, but meaningless).
 * The state is made again from the same document, selection and plugins; the pages are laid out again.
 */
export function resetTypingHistory(editor: Editor) {
  const { state } = editor;
  editor.view.updateState(ProseMirrorState.create({ doc: state.doc, selection: state.selection, plugins: state.plugins }));
  editor.view.dispatch(editor.state.tr.setMeta(REPAGINATE, true).setMeta("addToHistory", false));
}

/** What the editor's panels share: the document, the editor, what is selected,
 * and the way to change the document. */
export type EditorState = {
  document: Document;
  editor: Editor | null;
  selection: Selection;
  change: Change;
  flush: () => Promise<unknown>;
  /** Formatting in the editor the document can't keep, as of the last save. */
  notKept: string[];
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
