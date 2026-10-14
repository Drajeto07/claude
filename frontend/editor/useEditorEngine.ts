"use client";

import { useEditor } from "@tiptap/react";
import { useEffect, useMemo, useState } from "react";

import type { InsertableType } from "@/editor/AddElementMenu";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { useDocumentChanges, type EditorState } from "@/editor/EditorState";
import { editorExtensions } from "@/editor/extensions";
import { FloatWrap } from "@/editor/floatWrap";
import { HeadingNumbers, setHeadingNumbering } from "@/editor/headingNumbers";
import { hiddenWordCount } from "@/editor/hiddenText";
import { Pagination, REPAGINATE } from "@/editor/pagination";
import { chromeTarget, pageChrome, type PageChrome } from "@/editor/sectionHeaders";
import { useAutoSave } from "@/editor/useAutoSave";
import { useDocument } from "@/editor/useDocument";
import { useFormatting } from "@/editor/useFormatting";
import { useHistory } from "@/editor/useHistory";
import { usePageSettings, useRepaginate } from "@/editor/usePageSettings";
import { useSelection } from "@/editor/useSelection";
import { useNonce } from "@/lib/nonce";
import { addElement, addPage, clearPageSetting, errorMessage, renameDocument, setPageSetting, setSectionText } from "@/services/api";
import type { Document } from "@/types/document";

/** A page's header or footer edited (DOCX-015C), as the server call that makes it its section's own:
 * the last section's main ones through the page settings ("" or none clears the setting). */
function chromeEdit(document: Document, chrome: PageChrome | undefined, part: "header" | "footer", text: string | null) {
  const target = chromeTarget(document, chrome, part);
  return (documentId: string) =>
    target.kind === "settings"
      ? text
        ? setPageSetting(documentId, { property: target.property, value: text })
        : clearPageSetting(documentId, target.property)
      : setSectionText(documentId, { sectionId: target.sectionId, kind: target.key, text });
}

/**
 * Everything the document editor is, without how it is laid out (2.0 editor plan, E1): the document as server
 * state (useDocument), the Tiptap text engine with its pages, selection, autosave, formatting, undo/redo of saved
 * changes, hidden text and page chrome, and the actions the shells offer. The 1.x shell
 * (DocumentEditorShell) and the 2.0 shell (EditorShellV2) both lay out the same engine, so they behave alike.
 */
export function useEditorEngine(initialDocument: Document) {
  const { document, documentRef, setDocument, changedElsewhere } = useDocument(initialDocument);
  const page = usePageSettings(document.settings, document.lastSection);
  const { setPages } = page;

  // Pagination reads the page geometry from the page container's data-*
  // attributes (EditorCanvas), so the editor is never recreated when it changes.
  // Each heading's number, as Word numbers them (DOCX-016A), from the document's heading numbering (set below).
  const extensions = useMemo(() => [...editorExtensions, Pagination.configure({ onPages: setPages }), FloatWrap, HeadingNumbers], [setPages]);
  const nonce = useNonce();
  // What the editor opens with, made once: the shell renders on every keystroke, and making it
  // anew each time -- for nothing, the editor reads it only when made -- cost 28 ms a keystroke
  // at 12,000 blocks (PERF-005A).
  const initialContent = useMemo(() => documentToTiptapJSON(initialDocument), [initialDocument]);
  const editor = useEditor({
    extensions,
    content: initialContent,
    immediatelyRender: false,
    injectNonce: nonce,
    // The text area's name for screen readers (FEAT-011).
    editorProps: { attributes: { role: "textbox", "aria-label": "Document text", "aria-multiline": "true" } },
  });

  useEffect(() => {
    if (editor) setHeadingNumbering(editor, document.headingNumbering);
  }, [editor, document.headingNumbering]);

  const selection = useSelection(editor, document);
  const autosave = useAutoSave(editor, documentRef, setDocument);
  const { apply, change } = useDocumentChanges(editor, documentRef, setDocument, autosave.flush);
  const formatting = useFormatting(document, apply, autosave.flush);
  const history = useHistory(change);
  useRepaginate(editor, page);

  // A formatting job replaces the document when it finishes, so typing meanwhile
  // would be lost: the pages are read-only until it is done.
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.setEditable(!formatting.isApplying, false);
  }, [editor, formatting.isApplying]);

  const [actionError, setActionError] = useState<string | null>(null);

  // Word's hidden text (DOCX-025): hidden on the pages until asked for. Showing it
  // changes the blocks' heights, so the pages are laid out again.
  const hiddenWords = useMemo(() => hiddenWordCount(document.elements), [document.elements]);
  // Each page's header, footer and number, from the section it is in (DOCX-015).
  const chrome = useMemo(() => pageChrome(document, page.pages.map((slot) => slot.section)), [document, page.pages]);
  const [showHidden, setShowHidden] = useState(false);
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(REPAGINATE, true));
  }, [editor, showHidden]);

  async function run(action: (documentId: string) => Promise<Document>) {
    setActionError(null);
    try {
      await change(action);
    } catch (err) {
      setActionError(errorMessage(err, "That change couldn't be made."));
    }
  }
  const afterSelected = () => selection.selectedElementId ?? undefined;
  const addPageAfterSelection = () => run((documentId) => addPage(documentId, afterSelected()));
  const addElementAfterSelection = (elementType: InsertableType) => run((documentId) => addElement(documentId, { elementType, afterElementId: afterSelected() }));
  const rename = (title: string) => run((documentId) => renameDocument(documentId, title));
  const editChrome = (pageIndex: number, part: "header" | "footer", text: string | null) => run(chromeEdit(document, chrome[pageIndex], part, text));

  const editorState: EditorState = { document, editor, selection, change, flush: autosave.flush, notKept: autosave.notKept };

  return {
    document,
    changedElsewhere,
    editor,
    page,
    selection,
    autosave,
    formatting,
    history,
    editorState,
    hiddenWords,
    chrome,
    showHidden,
    toggleHidden: () => setShowHidden((shown) => !shown),
    actionError,
    clearActionError: () => setActionError(null),
    addPageAfterSelection,
    addElementAfterSelection,
    rename,
    editChrome,
  };
}

export type EditorEngine = ReturnType<typeof useEditorEngine>;
