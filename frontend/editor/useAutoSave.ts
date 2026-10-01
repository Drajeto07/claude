"use client";

import type { Transaction } from "@tiptap/pm/state";
import type { Editor } from "@tiptap/react";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { applyContentSaved, contentPatch } from "@/editor/contentPatch";
import { appliedStyle } from "@/editor/documentToTiptap";
import { reconcileWithIds, sameContent, UnsupportedContentError } from "@/editor/tiptapToDocument";
import { ApiError, getDocument, NetworkError, patchContent, RevisionConflictError, updateContent } from "@/services/api";
import type { ContentSaved, DirectStyle, Document, Element } from "@/types/document";

/** What the user is told about their typing (корекции.docx §29). "unsupported": the
 * editor holds content the document can't store; nothing is sent until it's gone. */
export type SaveStatus = "idle" | "saving" | "saved" | "error" | "offline" | "conflict" | "unsupported";

export const AUTOSAVE_DEBOUNCE_MS = 1200;
// Automatic retries after a failed save; offline, the last delay repeats until back.
const RETRY_DELAYS_MS = [5_000, 15_000, 60_000];

/** Gives each top-level block the element id it was saved under (new blocks,
 * and the second half of a split, get theirs here), so it stays the same element
 * from one save to the next. Changes attributes only, outside the undo history. */
// What the autosave writes into the editor itself (ids, the looks saved): not typing,
// so it schedules no save. Else a block a failed save gave an id would get a new one on
// every try, each one an update, and the editor would send the save again every
// AUTOSAVE_DEBOUNCE_MS instead of backing off.
const OWN_CHANGE = "autosaveOwnChange";

function syncElementIds(editor: Editor, nodeIds: (string | null)[]) {
  const { tr } = editor.state;
  editor.state.doc.forEach((node, offset, index) => {
    const id = nodeIds[index];
    if (id && node.attrs.elementId !== id) tr.setNodeAttribute(offset, "elementId", id);
  });
  if (tr.docChanged) editor.view.dispatch(tr.setMeta("addToHistory", false).setMeta(OWN_CHANGE, true));
}

/** Gives each top-level block the look the saved document gives it, so what the
 * editor shows is what was stored: a block split off a heading stops looking like
 * one, a new one takes its kind's style. Attributes only, outside the undo history. */
function syncAppliedStyles(editor: Editor, document: Document) {
  if (editor.isDestroyed) return;
  const byId = new Map(document.elements.map((element) => [element.id, element]));
  const { tr } = editor.state;
  editor.state.doc.forEach((node, offset) => {
    const element = node.attrs.elementId ? byId.get(node.attrs.elementId as string) : undefined;
    if (!element || !("style" in node.attrs)) return;
    const style = appliedStyle(element, document.resolvedStyles);
    if ((node.attrs.style ?? null) !== style) tr.setNodeAttribute(offset, "style", style);
  });
  if (tr.docChanged) editor.view.dispatch(tr.setMeta("addToHistory", false).setMeta(OWN_CHANGE, true));
}

// A patch the server didn't take that goes again as the whole document: it didn't fit
// the version it was made from (409), that version isn't the newest any more (412 --
// this tab's own write may have moved it on; the whole save says if another did), or
// it wasn't a patch the server could read (422, 428).
const PATCH_REFUSED = new Set([409, 412, 422, 428]);

/** One save of the editor's content: what changed since `base` (contentPatch) when
 * that is a patch and `base` says which revision it is, else the whole document; a
 * refused patch goes again whole. */
async function saveContent(base: Document, elements: Element[], styles: DirectStyle[]): Promise<Document> {
  const patch = typeof base.revision === "number" ? contentPatch(elements, base.elements, styles) : null;
  if (!patch) return updateContent(base.id, elements, styles);
  let saved: ContentSaved;
  try {
    saved = await patchContent(base.id, base.revision, patch);
  } catch (error) {
    if (error instanceof ApiError && PATCH_REFUSED.has(error.status)) return updateContent(base.id, elements, styles);
    throw error;
  }
  try {
    return applyContentSaved(base, elements.map((element) => element.id), saved);
  } catch {
    // The answer doesn't fit this editor's copy: the server has the save, so take its document.
    return getDocument(base.id);
  }
}

function statusAfter(error: unknown): SaveStatus {
  if (error instanceof RevisionConflictError) return "conflict";
  // More than a document can hold (too many pictures, too many of their bytes -- SEC-012,
  // or a request past the size cap): saving it again never gets through.
  if (error instanceof ApiError && error.status === 413) return "unsupported";
  // No answer while the browser knows it's offline; otherwise the server is at fault (retried).
  if (error instanceof NetworkError && typeof navigator !== "undefined" && !navigator.onLine) return "offline";
  return "error";
}

/**
 * Saves what is typed in the editor (корекции.docx §29):
 * - debounced: one request a moment after typing stops, never one per key (and
 *   the backend merges a burst of saves into one undo step);
 * - change-aware: it sends what changed since the last save and gets back what
 *   that changed, the whole document only past a threshold (contentPatch.ts);
 * - one at a time: whoever asks while a save runs waits for it, and then for
 *   anything typed since, so `flush()` resolving means everything typed before
 *   the call is on the server -- every other change to the document calls it
 *   first, and a failed flush stops that change instead of overwriting typing;
 * - status-aware: Saving…, Saved, Failed to save (retried after a pause, or at
 *   once with `retry`), Offline (retried when the connection is back) and
 *   Conflict (changed elsewhere: nothing more is sent until a reload);
 * - cancelable: pending work is saved when the editor goes away, and leaving the
 *   page while something is unsaved asks first.
 */
export function useAutoSave(editor: Editor | null, documentRef: RefObject<Document>, onSaved: (document: Document) => void) {
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [problem, setProblem] = useState<string | null>(null);
  // What the editor holds that the document can't keep (tiptapToDocument NOT_KEPT), as of the last save.
  const [notKept, setNotKept] = useState<string[]>([]);
  const statusRef = useRef<SaveStatus>("idle");
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failures = useRef(0);
  const inFlight = useRef<Promise<Document> | null>(null);
  const flushRef = useRef<() => Promise<Document>>(() => Promise.resolve(documentRef.current));

  const report = useCallback((next: SaveStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const flush = useCallback((): Promise<Document> => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    if (retryTimer.current) clearTimeout(retryTimer.current);
    debounceTimer.current = retryTimer.current = null;
    if (inFlight.current) return inFlight.current.then(() => flushRef.current());
    if (statusRef.current === "conflict") return Promise.reject(new RevisionConflictError());
    if (!editor || editor.isDestroyed) return Promise.resolve(documentRef.current);

    const content = (editor.getJSON().content ?? []) as Parameters<typeof reconcileWithIds>[0];
    let reconciled: ReturnType<typeof reconcileWithIds>;
    try {
      reconciled = reconcileWithIds(content, documentRef.current.elements, documentRef.current);
    } catch (error) {
      if (!(error instanceof UnsupportedContentError)) throw error;
      // Never save part of the document: the last saved version stays as it is.
      setProblem(error.message);
      report("unsupported");
      return Promise.reject(error);
    }
    setProblem(null);
    const { elements, nodeIds, styles } = reconciled;
    setNotKept((before) => (sameContent(before, reconciled.notes) ? before : reconciled.notes));
    syncElementIds(editor, nodeIds);
    if (styles.length === 0 && sameContent(elements, documentRef.current.elements)) return Promise.resolve(documentRef.current);

    report("saving");
    const save = saveContent(documentRef.current, elements, styles)
      .then(
        (saved) => {
          failures.current = 0;
          onSaved(saved);
          syncAppliedStyles(editor, saved);
          report("saved");
          return saved;
        },
        (error: unknown) => {
          const next = statusAfter(error);
          if (next === "unsupported") setProblem((error as ApiError).message);
          report(next);
          if (next === "offline" || (next === "error" && failures.current < RETRY_DELAYS_MS.length)) {
            const delay = RETRY_DELAYS_MS[Math.min(failures.current, RETRY_DELAYS_MS.length - 1)];
            failures.current += 1;
            retryTimer.current = setTimeout(() => void flushRef.current().catch(() => undefined), delay);
          }
          throw error;
        },
      )
      .finally(() => {
        inFlight.current = null;
      });
    inFlight.current = save;
    return save;
  }, [editor, documentRef, onSaved, report]);

  useEffect(() => {
    flushRef.current = flush;
  }, [flush]);

  // Typing schedules a save; leaving the editor saves at once.
  useEffect(() => {
    if (!editor) return;
    function schedule({ transaction }: { transaction: Transaction }) {
      if (transaction.getMeta(OWN_CHANGE)) return;
      if (statusRef.current === "saved") report("idle");
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => {
        debounceTimer.current = null;
        void flushRef.current().catch(() => undefined);
      }, AUTOSAVE_DEBOUNCE_MS);
    }
    function saveNow() {
      void flushRef.current().catch(() => undefined);
    }
    editor.on("update", schedule);
    editor.on("blur", saveNow);
    return () => {
      editor.off("update", schedule);
      editor.off("blur", saveNow);
    };
  }, [editor, report]);

  useEffect(() => {
    const unsaved = () => debounceTimer.current !== null || inFlight.current !== null || ["error", "offline", "unsupported"].includes(statusRef.current);
    function onOnline() {
      if (statusRef.current === "offline" || statusRef.current === "error") void flushRef.current().catch(() => undefined);
    }
    function onOffline() {
      if (unsaved()) report("offline");
    }
    function onBeforeUnload(event: BeforeUnloadEvent) {
      if (!unsaved()) return;
      void flushRef.current().catch(() => undefined);
      event.preventDefault();
    }
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("beforeunload", onBeforeUnload);
      // Leaving the editor inside the app (a link): what is still waiting goes now.
      if (debounceTimer.current) void flushRef.current().catch(() => undefined);
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [report]);

  const retry = useCallback(() => void flush().catch(() => undefined), [flush]);

  return { status, problem, notKept, flush, retry };
}
