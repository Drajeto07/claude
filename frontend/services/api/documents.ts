import { apiFetch, ApiError, jsonInit, jsonOrThrow, okOrThrow, SESSION_COOKIE } from "@/services/api/client";
import type { Document, Element, FormattingProperty, StyleAnalysisResult } from "@/types/document";

/** Fired on window when a write is rejected because the document changed elsewhere. */
export const REVISION_CONFLICT_EVENT = "smartdoc:revision-conflict";

export class RevisionConflictError extends ApiError {
  constructor(requestId: string | null = null) {
    const message = "This document was changed in another tab or window, so this change wasn't saved.";
    super(412, { code: "revision_conflict", message }, message, requestId);
    this.name = "RevisionConflictError";
  }
}

// The revision this tab last saw for each document, sent back as If-Match so the
// server can refuse a write based on an outdated copy (another tab, device or user).
const knownRevisions = new Map<string, number>();
// One write at a time per document: each response's revision must be recorded
// before the next write starts, or this tab would conflict with itself.
const writeQueues = new Map<string, Promise<unknown>>();

export function rememberRevision(document: Document): Document {
  if (typeof window !== "undefined") knownRevisions.set(document.id, document.revision);
  return document;
}

/**
 * Runs one write to a document after every earlier one has finished, with the
 * revision it is based on as If-Match. A 412 announces REVISION_CONFLICT_EVENT
 * and throws RevisionConflictError. `handle` reads the response while the
 * queue is still held, so a job-backed write can keep it until the job is done.
 */
export function documentWrite<T>(documentId: string, path: string, init: RequestInit, handle: (res: Response) => Promise<T>): Promise<T> {
  const previous = writeQueues.get(documentId) ?? Promise.resolve();
  const run = previous
    .catch(() => undefined)
    .then(async () => {
      const headers = new Headers(init.headers);
      const revision = knownRevisions.get(documentId);
      if (revision !== undefined) headers.set("If-Match", String(revision));
      const res = await apiFetch(path, { ...init, headers });
      if (res.status === 412) {
        window.dispatchEvent(new CustomEvent(REVISION_CONFLICT_EVENT, { detail: { documentId } }));
        throw new RevisionConflictError(res.headers.get("X-Request-ID"));
      }
      return handle(res);
    });
  writeQueues.set(documentId, run);
  return run;
}

async function documentOrThrow(res: Response, fallback: string): Promise<Document> {
  return rememberRevision(await jsonOrThrow<Document>(res, fallback));
}

/** `sessionToken`: on the Next.js server, which has no cookie jar, the signed-in
 * user's session cookie is forwarded explicitly. */
export async function getDocument(id: string, sessionToken?: string): Promise<Document> {
  const res = await apiFetch(`/api/documents/${encodeURIComponent(id)}`, {
    cache: "no-store",
    headers: sessionToken ? { Cookie: `${SESSION_COOKIE}=${sessionToken}` } : undefined,
  });
  return documentOrThrow(res, "Failed to fetch document");
}

function write(documentId: string, path: string, init: RequestInit, fallback: string): Promise<Document> {
  return documentWrite(documentId, path, init, (res) => documentOrThrow(res, fallback));
}

const documentPath = (documentId: string, rest = "") => `/api/documents/${encodeURIComponent(documentId)}${rest}`;

export function updateContent(documentId: string, elements: Element[]): Promise<Document> {
  return write(documentId, documentPath(documentId, "/content"), jsonInit("PUT", { elements }), "Failed to save edits");
}

export function addPage(documentId: string, afterElementId?: string | null): Promise<Document> {
  return write(documentId, documentPath(documentId, "/pages"), jsonInit("POST", { afterElementId: afterElementId ?? null }), "Failed to add a page");
}

export function addElement(
  documentId: string,
  input: { elementType: "paragraph" | "heading" | "list" | "table"; afterElementId?: string | null; text?: string },
): Promise<Document> {
  return write(documentId, documentPath(documentId, "/elements"), jsonInit("POST", input), "Failed to add element");
}

export function undoFormatting(documentId: string): Promise<Document> {
  return write(documentId, documentPath(documentId, "/undo"), { method: "POST" }, "Nothing to undo");
}

export function redoFormatting(documentId: string): Promise<Document> {
  return write(documentId, documentPath(documentId, "/redo"), { method: "POST" }, "Nothing to redo");
}

export function setElementStyle(
  documentId: string,
  elementId: string,
  input: { property: FormattingProperty; value: string; unit?: string | null },
): Promise<Document> {
  return write(documentId, documentPath(documentId, `/elements/${encodeURIComponent(elementId)}/style`), jsonInit("PATCH", input), "Failed to set style");
}

export function clearElementStyle(documentId: string, elementId: string, property: FormattingProperty): Promise<Document> {
  return write(documentId, documentPath(documentId, `/elements/${encodeURIComponent(elementId)}/style/${property}`), { method: "DELETE" }, "Failed to clear style");
}

export function renameDocument(documentId: string, title: string): Promise<Document> {
  return write(documentId, documentPath(documentId), jsonInit("PATCH", { title }), "Failed to rename document");
}

export function setPageSetting(documentId: string, input: { property: FormattingProperty; value: string; unit?: string | null }): Promise<Document> {
  return write(documentId, documentPath(documentId, "/settings"), jsonInit("PATCH", input), "Failed to set page setting");
}

export function clearPageSetting(documentId: string, property: FormattingProperty): Promise<Document> {
  return write(documentId, documentPath(documentId, `/settings/${property}`), { method: "DELETE" }, "Failed to clear page setting");
}

export async function analyzeStyle(documentId: string): Promise<StyleAnalysisResult> {
  return jsonOrThrow(await apiFetch(documentPath(documentId, "/style-analysis"), { method: "POST" }), "Failed to analyze style");
}

export async function deleteDocument(documentId: string): Promise<void> {
  await okOrThrow(await apiFetch(documentPath(documentId), { method: "DELETE" }), "Failed to delete the document");
}
