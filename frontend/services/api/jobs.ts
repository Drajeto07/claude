import { API_BASE_URL, API_PREFIX, apiFetch, ApiError, jsonInit, jsonOrThrow, NetworkError, okOrThrow } from "@/services/api/client";
import { documentWrite, getDocument } from "@/services/api/documents";
import type {
  Batch,
  ChunkedUpload,
  ConflictResolution,
  Document,
  ExportJobResult,
  FormatJobResult,
  FormattingConflict,
  ImportJobResult,
  Job,
  JobProgress,
  PdfMode,
  ReferenceStyle,
} from "@/types/document";

export type OnProgress = (progress: JobProgress) => void;

/** One template applied to many documents (FEAT-001): a format job for each, answered at once. */
export async function batchFormat(documentIds: string[], templateId: string): Promise<Batch> {
  const res = await apiFetch("/jobs/batch-format", jsonInit("POST", { documentIds, templateId }));
  return jsonOrThrow<Batch>(res, "Couldn't start formatting the documents");
}

/** Many documents translated into one language (FEAT-003): a translation job for each -- a new
 * document, its original untouched -- followed with getBatch. */
export async function batchTranslate(documentIds: string[], targetLanguage: string): Promise<Batch> {
  const res = await apiFetch("/jobs/batch-translate", jsonInit("POST", { documentIds, targetLanguage }));
  return jsonOrThrow<Batch>(res, "Couldn't start translating the documents");
}

/** Many documents exported into one ZIP (FEAT-002): one export job, downloaded from jobFileUrl
 * like any export; its result names each part and whether its words all came through. */
export async function batchExport(documentIds: string[], format: "docx" | "pdf", onProgress?: OnProgress): Promise<Job & { result: ExportJobResult }> {
  const done = await startJob("/jobs/batch-export", jsonInit("POST", { documentIds, format }), "Couldn't export the documents", onProgress);
  return { ...done, result: resultOf<ExportJobResult>(done) };
}

/** A batch's jobs and how far they have got. */
export async function getBatch(id: string): Promise<Batch> {
  return jsonOrThrow<Batch>(await apiFetch(`/jobs/batches/${encodeURIComponent(id)}`, { cache: "no-store" }), "Couldn't follow the batch");
}

export async function getJob(id: string): Promise<Job> {
  return jsonOrThrow(await apiFetch(`/jobs/${encodeURIComponent(id)}`, { cache: "no-store" }), "Couldn't check on the job");
}

/** The user's latest jobs, newest first (e.g. recent exports: type "export", status "succeeded"). */
export async function listJobs(params: { type?: Job["type"]; status?: Job["status"]; limit?: number } = {}): Promise<Job[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) query.set(key, String(value));
  return jsonOrThrow(await apiFetch(`/jobs?${query}`, { cache: "no-store" }), "Couldn't load recent activity");
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Polls a background job until it finishes, telling `onProgress` each real stage
 * and percentage the backend records (never a timer). A failed job throws with
 * its reason. */
export async function waitForJob(job: Job, onProgress?: OnProgress): Promise<Job> {
  let current = job;
  let delay = 300;
  for (;;) {
    onProgress?.({ stage: current.stage ?? "queued", progress: current.progress });
    if (current.status === "succeeded") return current;
    if (current.status === "failed") throw new ApiError(422, { code: "job_failed", message: current.error ?? "Processing failed." }, "Processing failed.", null);
    // Cancelled (e.g. from another tab, POST /jobs/{id}/cancel): nothing more will come, so stop polling.
    if (current.status === "cancelled") throw new ApiError(409, { code: "job_cancelled", message: "This was cancelled." }, "This was cancelled.", null);
    await sleep(delay);
    delay = Math.min(delay * 1.5, 1500);
    current = await getJob(current.id);
  }
}

/** A finished job's result, as its kind of job produces it (backend schemas/jobs.py). */
function resultOf<T>(job: Job): T {
  return job.result as T;
}

async function startJob(path: string, init: RequestInit, fallback: string, onProgress?: OnProgress): Promise<Job> {
  return waitForJob(await jsonOrThrow<Job>(await apiFetch(path, init), fallback), onProgress);
}

/** Pasted text into a new document, analyzed in a background job. */
export async function importText(text: string, title?: string, onProgress?: OnProgress): Promise<Document> {
  const done = await startJob("/jobs/import-text", jsonInit("POST", { text, title }), "Failed to create document", onProgress);
  return getDocument(resultOf<ImportJobResult>(done).documentId);
}

/** An uploaded .docx/.pdf/.txt into a new document: uploaded, then read in a background job.
 * `autolink`: turn a Word file's web and e-mail addresses written as plain text into links
 * (off: they stay text, as the file has them -- DOCX-026). `pdfMode`: a PDF as an editable
 * document (the default) or layout-focused -- its pages and look kept (P2E-007). */
export async function importFile(
  file: File,
  title?: string,
  onProgress?: OnProgress,
  options: { autolink?: boolean; pdfMode?: PdfMode } = {},
): Promise<Document> {
  onProgress?.({ stage: "uploading", progress: 0 });
  if (file.size > WHOLE_UPLOAD_MAX_BYTES) {
    const done = await waitForJob(await importInParts(file, title, options, onProgress), onProgress);
    return getDocument(resultOf<ImportJobResult>(done).documentId);
  }
  const formData = new FormData();
  formData.append("file", file);
  if (title) formData.append("title", title);
  if (options.autolink) formData.append("autolink", "true");
  if (options.pdfMode === "layout") formData.append("pdf_mode", "layout");
  // No manual Content-Type here -- the browser sets the multipart boundary itself.
  const done = await startJob("/jobs/import-file", { method: "POST", body: formData }, "Failed to upload document", onProgress);
  return getDocument(resultOf<ImportJobResult>(done).documentId);
}

/** The largest file sent in one request (B-035A). The hosting takes requests of up to 4.5 MB (Vercel's limit,
 * a 413 before the app sees one), so a larger file goes up in parts of the size the server gives (3 MiB). */
export const WHOLE_UPLOAD_MAX_BYTES = 3 * 1024 * 1024;

// A part, the start or the completion that didn't get through for a passing reason is sent again after these.
const UPLOAD_RETRY_DELAYS_MS = [500, 1500, 4000];
const PASSING = new Set([408, 429, 500, 502, 503, 504]);

/** `attempt`, again after a pause while it fails for a passing reason (no connection, the server busy); then an
 * error that says the upload was interrupted -- never that it worked. Safe for parts (each overwrites itself)
 * and completion (one job per upload, the server's Idempotency-Key). */
async function retried<T>(attempt: () => Promise<T>): Promise<T> {
  for (let tries = 0; ; tries += 1) {
    try {
      return await attempt();
    } catch (error) {
      const passing = error instanceof NetworkError || (error instanceof ApiError && PASSING.has(error.status));
      if (!passing) throw error;
      if (tries >= UPLOAD_RETRY_DELAYS_MS.length) {
        const message = "The upload was interrupted. Check your connection and upload the file again.";
        throw new ApiError(0, { code: "upload_interrupted", message }, message, null);
      }
      await sleep(UPLOAD_RETRY_DELAYS_MS[tries]);
    }
  }
}

async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** A file too large for one request, sent in parts (B-035A, backend app/jobs/uploads.py): started with its size and
 * SHA-256, each part sent with its own SHA-256 (any part may be sent again), then completed -- only then does the
 * server check the whole file and make the import job, the same job a file sent whole makes. Only headers the API's
 * CORS policy allows are sent (Content-Type): during development the API is on another origin. */
async function importInParts(file: File, title: string | undefined, options: { autolink?: boolean; pdfMode?: PdfMode }, onProgress?: OnProgress): Promise<Job> {
  const sha256 = await sha256Hex(file);
  const body = { filename: file.name, size: file.size, sha256, contentType: file.type || null, title: title ?? null, autolink: Boolean(options.autolink), pdfMode: options.pdfMode ?? "editable" };
  const upload = await retried(async () => jsonOrThrow<ChunkedUpload>(await apiFetch("/jobs/import-file/uploads", jsonInit("POST", body)), "Failed to upload document"));
  const path = `/jobs/import-file/uploads/${encodeURIComponent(upload.uploadId)}`;
  for (let index = 0; index < upload.chunks; index += 1) {
    const part = file.slice(index * upload.chunkSize, Math.min(file.size, (index + 1) * upload.chunkSize));
    // The part's SHA-256 as a query parameter: the API's CORS policy allows no other request headers than its own.
    const partPath = `${path}/parts/${index}?sha256=${await sha256Hex(part)}`;
    const init = { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: part };
    await retried(async () => okOrThrow(await apiFetch(partPath, init), "Failed to upload document"));
    // The upload's share of the stage: its parts as they arrive (the server's stages follow).
    onProgress?.({ stage: "uploading", progress: Math.round(((index + 1) / upload.chunks) * 100) });
  }
  // Completing again (a retry) answers the same job: the server gives each upload its own Idempotency-Key.
  return retried(async () => jsonOrThrow<Job>(await apiFetch(`${path}/complete`, { method: "POST" }), "Failed to upload document"));
}

/** A translated version of a document (TRAN-006): a new document, linked to the original,
 * which isn't changed. Resolves to the new document's id. */
export async function translateDocument(documentId: string, targetLanguage: string, sourceLanguage?: string | null, onProgress?: OnProgress): Promise<string> {
  const done = await startJob(
    "/jobs/translate-document",
    jsonInit("POST", { documentId, targetLanguage, sourceLanguage: sourceLanguage || null }),
    "Couldn't translate the document",
    onProgress,
  );
  return resultOf<ImportJobResult>(done).documentId;
}

/** Format by Example: reads the look of a reference .docx. Saves nothing; pass
 * its styleSystem to createTemplate to keep it. */
export async function extractReferenceStyle(file: File, onProgress?: OnProgress): Promise<ReferenceStyle> {
  onProgress?.({ stage: "uploading", progress: 0 });
  const formData = new FormData();
  formData.append("file", file);
  const done = await startJob("/jobs/extract-reference", { method: "POST", body: formData }, "Couldn't read the reference document", onProgress);
  return resultOf<ReferenceStyle>(done);
}

export type ExportOptions = { includeHeaders: boolean; includePageNumbers: boolean; includePageBreaks: boolean };

/** A DOCX or PDF rendered in a background job; download it from jobFileUrl(job.id). */
export async function exportDocument(documentId: string, format: "docx" | "pdf", options: ExportOptions, onProgress?: OnProgress): Promise<Job & { result: ExportJobResult }> {
  const done = await startJob("/jobs/export", jsonInit("POST", { documentId, format, ...options }), "Failed to export", onProgress);
  return { ...done, result: resultOf<ExportJobResult>(done) };
}

export function jobFileUrl(jobId: string): string {
  return `${API_BASE_URL}${API_PREFIX}/jobs/${encodeURIComponent(jobId)}/file`;
}

export type FormatResult =
  | { status: "applied"; document: Document; aiUnavailable: boolean; instructionEditCount: number; proposalCount: number }
  | { status: "conflicts"; conflicts: FormattingConflict[] };

export function formatDocument(
  documentId: string,
  options: {
    templateId?: string;
    instructionsText?: string;
    instructionsFile?: File;
    resolutions?: ConflictResolution[];
    onProgress?: OnProgress;
  },
): Promise<FormatResult> {
  const formData = new FormData();
  formData.append("documentId", documentId);
  if (options.templateId) formData.append("templateId", options.templateId);
  if (options.instructionsText) formData.append("instructionsText", options.instructionsText);
  if (options.instructionsFile) formData.append("instructionsFile", options.instructionsFile);
  if (options.resolutions) formData.append("resolutions", JSON.stringify(options.resolutions));

  // The job changes the document's revision, so it holds this document's write
  // queue until it has finished and the new revision is known -- an autosave
  // queued meanwhile then goes out with the right If-Match instead of a 412.
  return documentWrite(documentId, "/jobs/format", { method: "POST", body: formData }, async (res) => {
    const done = await waitForJob(await jsonOrThrow<Job>(res, "Failed to apply formatting"), options.onProgress);
    const result = resultOf<FormatJobResult>(done);
    if (result.status === "conflicts") return { status: "conflicts", conflicts: result.conflicts };
    return {
      status: "applied",
      document: await getDocument(documentId),
      aiUnavailable: result.aiUnavailable,
      instructionEditCount: result.instructionEditCount,
      proposalCount: result.proposalCount ?? 0,
    };
  });
}
