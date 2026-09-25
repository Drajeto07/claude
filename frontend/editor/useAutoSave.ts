"use client";

import type { Editor } from "@tiptap/react";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { reconcileWithIds, sameContent } from "@/editor/tiptapToDocument";
import { NetworkError, RevisionConflictError, updateContent } from "@/services/api";
import type { Document } from "@/types/document";

/** What the user is told about their typing (корекции.docx §29). */
export type SaveStatus = "idle" | "saving" | "saved" | "error" | "offline" | "conflict";

export const AUTOSAVE_DEBOUNCE_MS = 1200;
// Automatic retries after a failed save; offline, the last delay repeats until back.
const RETRY_DELAYS_MS = [5_000, 15_000, 60_000];

/** Gives each top-level block the element id it was saved under (new blocks,
 * and the second half of a split, get theirs here), so it stays the same element
 * from one save to the next. Changes attributes only, outside the undo history. */
function syncElementIds(editor: Editor, nodeIds: (string | null)[]) {
  const { tr } = editor.state;
  editor.state.doc.forEach((node, offset, index) => {
    const id = nodeIds[index];
    if (id && node.attrs.elementId !== id) tr.setNodeAttribute(offset, "elementId", id);
  });
  if (tr.docChanged) editor.view.dispatch(tr.setMeta("addToHistory", false));
}

function statusAfter(error: unknown): SaveStatus {
  if (error instanceof RevisionConflictError) return "conflict";
  // No answer while the browser knows it's offline; otherwise the server is at fault (retried).
  if (error instanceof NetworkError && typeof navigator !== "undefined" && !navigator.onLine) return "offline";
  return "error";
}

/**
 * Saves what is typed in the editor (корекции.docx §29):
 * - debounced: one request a moment after typing stops, never one per key (and
 *   the backend merges a burst of saves into one undo step);
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
    const { elements, nodeIds } = reconcileWithIds(content, documentRef.current.elements);
    syncElementIds(editor, nodeIds);
    if (sameContent(elements, documentRef.current.elements)) return Promise.resolve(documentRef.current);

    report("saving");
    const save = updateContent(documentRef.current.id, elements)
      .then(
        (saved) => {
          failures.current = 0;
          onSaved(saved);
          report("saved");
          return saved;
        },
        (error: unknown) => {
          const next = statusAfter(error);
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
    function schedule() {
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
    const unsaved = () => debounceTimer.current !== null || inFlight.current !== null || ["error", "offline"].includes(statusRef.current);
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

  return { status, flush, retry };
}
