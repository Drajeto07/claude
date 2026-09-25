import type {
  ConflictResolution,
  CreatedTemplate,
  Document,
  Element,
  FormattingConflict,
  FormattingProperty,
  ReferenceStyle,
  StyleAnalysisResult,
  StylePreview,
  StyleSystem,
  Template,
  TemplateVersion,
  TemplateVisibility,
} from "@/types/document";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const SESSION_COOKIE = "smartdoc_session";

/** Fired on window when a write is rejected because the document changed elsewhere. */
export const REVISION_CONFLICT_EVENT = "smartdoc:revision-conflict";

export class UnauthorizedError extends Error {
  constructor() {
    super("Not signed in");
  }
}

export class RevisionConflictError extends Error {
  constructor() {
    super("This document was changed in another tab or window, so this change wasn't saved.");
  }
}

export type CurrentUser = { id: string; email: string; fullName: string | null; workspaceId: string };

const ASSET_URL_PREFIX = `${API_BASE_URL}/api/assets/`;

/** A stored image, fetched with the session cookie (same-site, so an <img> sends it). */
export function assetUrl(assetId: string): string {
  return `${ASSET_URL_PREFIX}${encodeURIComponent(assetId)}`;
}

/** The inverse of assetUrl, for turning an editor image node back into an asset reference. */
export function assetIdFromUrl(src: string): string | null {
  return src.startsWith(ASSET_URL_PREFIX) ? decodeURIComponent(src.slice(ASSET_URL_PREFIX.length)) : null;
}

/** Only same-site relative paths, so `?next=` can't become an open redirect. */
export function safeNextPath(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

/** Every call to a signed-in endpoint goes through here: the session cookie is
 * always sent, and a 401 in the browser sends the user to /login and back. */
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, credentials: "include" });
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      const next = window.location.pathname + window.location.search;
      // Plain module, no router hook available; a full load also drops any stale state.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    throw new UnauthorizedError();
  }
  return res;
}

async function errorDetail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : `${fallback} (${res.status})`;
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

function documentWrite<T>(
  documentId: string,
  path: string,
  init: RequestInit,
  handle: (res: Response) => Promise<T>,
): Promise<T> {
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
        throw new RevisionConflictError();
      }
      return handle(res);
    });
  writeQueues.set(documentId, run);
  return run;
}

async function documentOrThrow(res: Response, fallback: string): Promise<Document> {
  if (!res.ok) throw new Error(await errorDetail(res, fallback));
  return rememberRevision(await res.json());
}

async function authRequest(path: string, body: object): Promise<CurrentUser> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 422) throw new Error("Enter a valid email and a password of at least 8 characters.");
  if (!res.ok) throw new Error(await errorDetail(res, "Request failed"));
  return res.json();
}

export function register(email: string, password: string, fullName?: string): Promise<CurrentUser> {
  return authRequest("/api/auth/register", { email, password, fullName: fullName?.trim() || null });
}

export function login(email: string, password: string): Promise<CurrentUser> {
  return authRequest("/api/auth/login", { email, password });
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/auth/logout`, { method: "POST", credentials: "include" });
}

/** null when nobody is signed in -- unlike apiFetch, never redirects. */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch(`${API_BASE_URL}/api/auth/me`, { credentials: "include", cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Failed to load the signed-in user (${res.status})`);
  return res.json();
}

export async function createDocument(text: string, title?: string): Promise<Document> {
  const res = await apiFetch("/api/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  return documentOrThrow(res, "Failed to create document");
}

/** `sessionToken` is for server components: the Next.js server has no browser
 * cookie jar, so it forwards the incoming request's session cookie explicitly. */
export async function getDocument(id: string, sessionToken?: string): Promise<Document> {
  const res = await apiFetch(`/api/documents/${id}`, {
    cache: "no-store",
    headers: sessionToken ? { Cookie: `${SESSION_COOKIE}=${sessionToken}` } : undefined,
  });
  return documentOrThrow(res, "Failed to fetch document");
}

export async function uploadDocument(file: File, title?: string): Promise<Document> {
  const formData = new FormData();
  formData.append("file", file);
  if (title) formData.append("title", title);

  // No manual Content-Type here -- the browser sets the multipart boundary itself.
  const res = await apiFetch("/api/documents/upload", { method: "POST", body: formData });
  return documentOrThrow(res, "Failed to upload document");
}

export class TemplateConflictError extends Error {
  constructor() {
    super("This template was changed in another tab or by someone else, so your edit wasn't saved.");
  }
}

async function jsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (res.status === 412) throw new TemplateConflictError();
  if (!res.ok) throw new Error(await errorDetail(res, fallback));
  return res.json();
}

function jsonInit(method: string, body: unknown, version?: number | null): RequestInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // The version this page loaded: the server refuses the write (412) if it moved on since.
  if (version != null) headers["If-Match"] = String(version);
  return { method, headers, body: JSON.stringify(body) };
}

export async function listTemplates(): Promise<Template[]> {
  return jsonOrThrow(await apiFetch("/api/templates", { cache: "no-store" }), "Failed to fetch templates");
}

export async function getTemplate(id: string): Promise<Template> {
  return jsonOrThrow(await apiFetch(`/api/templates/${encodeURIComponent(id)}`, { cache: "no-store" }), "Failed to load the template");
}

/** From a style system, from a document's current look (`sourceDocumentId`), or blank. */
export async function createTemplate(input: {
  name: string;
  category?: string;
  description?: string;
  visibility?: TemplateVisibility;
  styleSystem?: StyleSystem;
  sourceDocumentId?: string;
}): Promise<CreatedTemplate> {
  return jsonOrThrow(await apiFetch("/api/templates", jsonInit("POST", input)), "Failed to create the template");
}

export async function updateTemplate(
  id: string,
  version: number | null,
  changes: { name?: string; category?: string; description?: string; visibility?: TemplateVisibility; styleSystem?: StyleSystem },
): Promise<Template> {
  return jsonOrThrow(await apiFetch(`/api/templates/${encodeURIComponent(id)}`, jsonInit("PUT", changes, version)), "Failed to save the template");
}

export async function deleteTemplate(id: string): Promise<void> {
  const res = await apiFetch(`/api/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await errorDetail(res, "Failed to delete the template"));
}

export async function duplicateTemplate(id: string, name?: string): Promise<Template> {
  return jsonOrThrow(
    await apiFetch(`/api/templates/${encodeURIComponent(id)}/duplicate`, jsonInit("POST", name ? { name } : {})),
    "Failed to duplicate the template",
  );
}

/** null clears the workspace default. */
export async function setDefaultTemplate(templateId: string | null): Promise<string | null> {
  const body = await jsonOrThrow<{ templateId: string | null }>(
    await apiFetch("/api/templates/default", jsonInit("PUT", { templateId })),
    "Failed to change the default template",
  );
  return body.templateId;
}

export async function listTemplateVersions(id: string): Promise<TemplateVersion[]> {
  return jsonOrThrow(await apiFetch(`/api/templates/${encodeURIComponent(id)}/versions`, { cache: "no-store" }), "Failed to load the history");
}

export async function restoreTemplateVersion(id: string, number: number, version: number | null): Promise<Template> {
  return jsonOrThrow(
    await apiFetch(`/api/templates/${encodeURIComponent(id)}/versions/${number}/restore`, jsonInit("POST", {}, version)),
    "Failed to restore that version",
  );
}

/** How a document would look under an unsaved style system, resolved by the real engine. */
export async function previewStyleSystem(styleSystem: StyleSystem, signal?: AbortSignal): Promise<StylePreview> {
  return jsonOrThrow(await apiFetch("/api/templates/preview", { ...jsonInit("POST", styleSystem), signal }), "Failed to preview");
}

/** Format by Example: reads the look of a reference .docx. Saves nothing; pass
 * its styleSystem to createTemplate to keep it. */
export async function extractReferenceStyle(file: File): Promise<ReferenceStyle> {
  const formData = new FormData();
  formData.append("file", file);
  return jsonOrThrow(await apiFetch("/api/templates/extract", { method: "POST", body: formData }), "Couldn't read the reference document");
}

export type FormatResult =
  | { status: "applied"; document: Document; aiUnavailable: boolean; instructionEditCount: number }
  | { status: "conflicts"; conflicts: FormattingConflict[] };

export function formatDocument(
  documentId: string,
  options: {
    templateId?: string;
    instructionsText?: string;
    instructionsFile?: File;
    resolutions?: ConflictResolution[];
  },
): Promise<FormatResult> {
  const formData = new FormData();
  if (options.templateId) formData.append("templateId", options.templateId);
  if (options.instructionsText) formData.append("instructionsText", options.instructionsText);
  if (options.instructionsFile) formData.append("instructionsFile", options.instructionsFile);
  if (options.resolutions) formData.append("resolutions", JSON.stringify(options.resolutions));

  return documentWrite(documentId, `/api/documents/${documentId}/format`, { method: "POST", body: formData }, async (res) => {
    if (res.status === 409) {
      const body = await res.json();
      return { status: "conflicts", conflicts: body.detail.conflicts as FormattingConflict[] };
    }
    if (!res.ok) throw new Error(await errorDetail(res, "Failed to apply formatting"));
    const body = await res.json();
    return {
      status: "applied",
      document: rememberRevision(body.document as Document),
      aiUnavailable: Boolean(body.aiUnavailable),
      instructionEditCount: Number(body.instructionEditCount ?? 0),
    };
  });
}

function jsonWrite(documentId: string, path: string, method: string, body: unknown, fallback: string): Promise<Document> {
  return documentWrite(
    documentId,
    path,
    { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    (res) => documentOrThrow(res, fallback),
  );
}

function bareWrite(documentId: string, path: string, method: string, fallback: string): Promise<Document> {
  return documentWrite(documentId, path, { method }, (res) => documentOrThrow(res, fallback));
}

export function updateContent(documentId: string, elements: Element[]): Promise<Document> {
  return jsonWrite(documentId, `/api/documents/${documentId}/content`, "PUT", { elements }, "Failed to save edits");
}

export function addPage(documentId: string, afterElementId?: string | null): Promise<Document> {
  return jsonWrite(documentId, `/api/documents/${documentId}/pages`, "POST", { afterElementId: afterElementId ?? null }, "Failed to add a page");
}

export function undoFormatting(documentId: string): Promise<Document> {
  return bareWrite(documentId, `/api/documents/${documentId}/undo`, "POST", "Nothing to undo");
}

export function redoFormatting(documentId: string): Promise<Document> {
  return bareWrite(documentId, `/api/documents/${documentId}/redo`, "POST", "Nothing to redo");
}

export function setElementStyle(
  documentId: string,
  elementId: string,
  input: { property: FormattingProperty; value: string; unit?: string | null },
): Promise<Document> {
  return jsonWrite(documentId, `/api/documents/${documentId}/elements/${elementId}/style`, "PATCH", input, "Failed to set style");
}

export function clearElementStyle(documentId: string, elementId: string, property: FormattingProperty): Promise<Document> {
  return bareWrite(documentId, `/api/documents/${documentId}/elements/${elementId}/style/${property}`, "DELETE", "Failed to clear style");
}

export function renameDocument(documentId: string, title: string): Promise<Document> {
  return jsonWrite(documentId, `/api/documents/${documentId}`, "PATCH", { title }, "Failed to rename document");
}

export function setPageSetting(
  documentId: string,
  input: { property: FormattingProperty; value: string; unit?: string | null },
): Promise<Document> {
  return jsonWrite(documentId, `/api/documents/${documentId}/settings`, "PATCH", input, "Failed to set page setting");
}

export function clearPageSetting(documentId: string, property: FormattingProperty): Promise<Document> {
  return bareWrite(documentId, `/api/documents/${documentId}/settings/${property}`, "DELETE", "Failed to clear page setting");
}

export function addElement(
  documentId: string,
  input: { elementType: "paragraph" | "heading" | "list" | "table"; afterElementId?: string | null; text?: string },
): Promise<Document> {
  return jsonWrite(documentId, `/api/documents/${documentId}/elements`, "POST", input, "Failed to add element");
}

export async function analyzeStyle(documentId: string): Promise<StyleAnalysisResult> {
  const res = await apiFetch(`/api/documents/${documentId}/style-analysis`, { method: "POST" });
  if (!res.ok) throw new Error(await errorDetail(res, "Failed to analyze style"));
  return res.json();
}
