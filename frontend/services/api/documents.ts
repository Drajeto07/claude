import { apiFetch, ApiError, jsonInit, jsonOrThrow, okOrThrow, SESSION_COOKIE } from "@/services/api/client";
import type {
  ContentPatch,
  ContentSaved,
  DirectStyle,
  Document,
  DocumentComparison,
  DocumentList,
  DocumentVersion,
  Element,
  DocumentLanguage,
  DocumentStylePreview,
  FormattingProperty,
  GlossaryTerm,
  AcceptProposalsResponse,
  AccessibilityReport,
  ChangeCategory,
  HealthFixesResponse,
  HealthReport,
  StyleAnalysisResult,
  StyleSystem,
  TranslateResponse,
} from "@/types/document";

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
 * revision it is based on as If-Match: the last one this tab saw, or `revision`
 * when the write says which. A 412 announces REVISION_CONFLICT_EVENT (unless
 * `quiet`: the caller decides what it means) and throws RevisionConflictError.
 * `handle` reads the response while the queue is still held, so a job-backed
 * write can keep it until the job is done.
 */
export function documentWrite<T>(
  documentId: string,
  path: string,
  init: RequestInit,
  handle: (res: Response) => Promise<T>,
  options: { revision?: number; quiet?: boolean } = {},
): Promise<T> {
  const previous = writeQueues.get(documentId) ?? Promise.resolve();
  const run = previous
    .catch(() => undefined)
    .then(async () => {
      const headers = new Headers(init.headers);
      const revision = options.revision ?? knownRevisions.get(documentId);
      if (revision !== undefined) headers.set("If-Match", String(revision));
      const res = await apiFetch(path, { ...init, headers });
      if (res.status === 412) {
        if (!options.quiet) window.dispatchEvent(new CustomEvent(REVISION_CONFLICT_EVENT, { detail: { documentId } }));
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
  const res = await apiFetch(`/documents/${encodeURIComponent(id)}`, {
    cache: "no-store",
    headers: sessionToken ? { Cookie: `${SESSION_COOKIE}=${sessionToken}` } : undefined,
  });
  return documentOrThrow(res, "Failed to fetch document");
}

function write(documentId: string, path: string, init: RequestInit, fallback: string): Promise<Document> {
  return documentWrite(documentId, path, init, (res) => documentOrThrow(res, fallback));
}

const documentPath = (documentId: string, rest = "") => `/documents/${encodeURIComponent(documentId)}${rest}`;

/** styles: alignment or a picture's width the editor holds on top-level blocks,
 * kept as those elements' own style. */
export function updateContent(documentId: string, elements: Element[], styles: DirectStyle[] = []): Promise<Document> {
  return write(documentId, documentPath(documentId, "/content"), jsonInit("PUT", { elements, styles }), "Failed to save edits");
}

/**
 * Saves what changed since `revision`, the version the patch was made from
 * (PATCH /content, PERF-003). A 412 isn't announced: the caller then sends the
 * whole document, whose own answer says whether it was changed elsewhere.
 */
export function patchContent(documentId: string, revision: number, patch: ContentPatch): Promise<ContentSaved> {
  return documentWrite(
    documentId,
    documentPath(documentId, "/content"),
    jsonInit("PATCH", patch),
    async (res) => {
      const saved = await jsonOrThrow<ContentSaved>(res, "Failed to save edits");
      knownRevisions.set(documentId, saved.revision);
      return saved;
    },
    { revision, quiet: true },
  );
}

/** Applies one change to the content an AI instruction proposed. */
export function acceptProposal(documentId: string, proposalId: string): Promise<Document> {
  return write(documentId, documentPath(documentId, `/proposals/${encodeURIComponent(proposalId)}/accept`), { method: "POST" }, "Couldn't make that change");
}

/** Every waiting change of one category, accepted at once as one undo step (REV-003). The server
 * refuses the content's, and leaves waiting any change that would alter the words. */
export function acceptProposalsOfCategory(documentId: string, category: ChangeCategory): Promise<AcceptProposalsResponse> {
  return documentWrite(documentId, documentPath(documentId, "/proposals/accept"), jsonInit("POST", { category }), async (res) => {
    const answer = await jsonOrThrow<AcceptProposalsResponse>(res, "Couldn't accept those changes");
    rememberRevision(answer.document);
    return answer;
  });
}

/** Drops one proposed change; the document's content stays as it is. */
export function rejectProposal(documentId: string, proposalId: string): Promise<Document> {
  return write(documentId, documentPath(documentId, `/proposals/${encodeURIComponent(proposalId)}/reject`), { method: "POST" }, "Couldn't dismiss that change");
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

/** What a Word export does with the file's tracked changes (DOCX-022): keeps them in the
 * blocks not changed here ("kept"), or they are all accepted ("accepted"). The content
 * stays as it is: the import read it as accepted either way. */
export function setTrackedChanges(documentId: string, choice: NonNullable<Document["trackedChanges"]>): Promise<Document> {
  return write(documentId, documentPath(documentId, "/tracked-changes"), jsonInit("PUT", { choice }), "Couldn't change what happens to the tracked changes");
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

/** Deletes the document for good, with its version history and export files. */
export async function deleteDocument(documentId: string): Promise<void> {
  await okOrThrow(await apiFetch(documentPath(documentId), { method: "DELETE" }), "Failed to delete the document");
}

export type DocumentListParams = { q?: string; sort?: "updated" | "created" | "title"; limit?: number; offset?: number };

/** The documents the user can open, a page at a time. */
export async function listDocuments(params: DocumentListParams = {}): Promise<DocumentList> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== "") query.set(key, String(value));
  return jsonOrThrow(await apiFetch(`/documents?${query}`, { cache: "no-store" }), "Failed to load your documents");
}

export async function listVersions(documentId: string): Promise<DocumentVersion[]> {
  return jsonOrThrow(await apiFetch(documentPath(documentId, "/versions"), { cache: "no-store" }), "Failed to load the history");
}

/** The document as it was at one version, to look at. */
export async function getVersion(documentId: string, number: number): Promise<Document> {
  return jsonOrThrow(await apiFetch(documentPath(documentId, `/versions/${number}`), { cache: "no-store" }), "Failed to load that version");
}

/** Makes an earlier version current again, as a new change (it can be undone). */
export function restoreVersion(documentId: string, number: number): Promise<Document> {
  return write(documentId, documentPath(documentId, `/versions/${number}/restore`), { method: "POST" }, "Failed to restore that version");
}

/** What changed between two versions; by default the original against now (before/after). */
export async function compareVersions(documentId: string, from = 1, to?: number): Promise<DocumentComparison> {
  const query = new URLSearchParams({ from: String(from) });
  if (to !== undefined) query.set("to", String(to));
  return jsonOrThrow(await apiFetch(documentPath(documentId, `/compare?${query}`), { cache: "no-store" }), "Failed to compare the versions");
}

/** Document Health: deterministic checks of the saved document. */
export async function getHealth(documentId: string): Promise<HealthReport> {
  return jsonOrThrow(await apiFetch(documentPath(documentId, "/health"), { cache: "no-store" }), "Failed to check the document");
}

/** The accessibility checker (FEAT-010): deterministic checks of the saved document. */
export async function getAccessibility(documentId: string): Promise<AccessibilityReport> {
  return jsonOrThrow(await apiFetch(documentPath(documentId, "/accessibility"), { cache: "no-store" }), "Failed to check accessibility");
}

/** Document Health's fixes for these checks (every check's when none are named), proposed for
 * review: nothing changes until each is accepted (HLTH-002). */
export function proposeHealthFixes(documentId: string, checkIds?: string[]): Promise<HealthFixesResponse> {
  return documentWrite(documentId, documentPath(documentId, "/health/fixes"), jsonInit("POST", { checkIds: checkIds ?? null }), async (res) => {
    const answer = await jsonOrThrow<HealthFixesResponse>(res, "Couldn't work out the fixes");
    rememberRevision(answer.document);
    return answer;
  });
}

/** Blocks (or part of one block's text) translated as proposals to review (TRAN-005): nothing
 * in the document changes until one is accepted. */
export function translateBlocks(
  documentId: string,
  request: { elementIds: string[]; targetLanguage: string; sourceLanguage?: string | null; selection?: { start: number; end: number } | null },
): Promise<TranslateResponse> {
  return documentWrite(documentId, documentPath(documentId, "/translate"), jsonInit("POST", request), async (res) => {
    const answer = await jsonOrThrow<TranslateResponse>(res, "Couldn't translate that");
    rememberRevision(answer.document);
    return answer;
  });
}

/** The document's language: as set, as its text reads, its script and direction (TRAN-007). */
export async function getDocumentLanguage(documentId: string): Promise<DocumentLanguage> {
  return jsonOrThrow<DocumentLanguage>(await apiFetch(documentPath(documentId, "/language"), { cache: "no-store" }), "Couldn't read the document's language");
}

/** The document's language as the user says it is; null: detect it. */
export function setDocumentLanguage(documentId: string, language: string | null): Promise<Document> {
  return write(documentId, documentPath(documentId, "/language"), jsonInit("PUT", { language }), "Couldn't set the language");
}

/** How terms are to be translated in this document (TRAN-004). */
export function setGlossary(documentId: string, terms: GlossaryTerm[]): Promise<Document> {
  return write(documentId, documentPath(documentId, "/glossary"), jsonInit("PUT", { terms }), "Couldn't save the glossary");
}

/** The document with a look tried on -- before and after, what changes -- nothing saved (FMT-003). */
export async function previewStyle(documentId: string, styleSystem: StyleSystem): Promise<DocumentStylePreview> {
  return jsonOrThrow<DocumentStylePreview>(
    await apiFetch(documentPath(documentId, "/style-preview"), jsonInit("POST", { styleSystem })),
    "Couldn't preview that look",
  );
}
