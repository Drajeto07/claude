import { API_BASE_URL, apiFetch, ApiError, jsonInit, jsonOrThrow } from "@/services/api/client";
import { documentWrite, getDocument } from "@/services/api/documents";
import type {
  ConflictResolution,
  Document,
  ExportJobResult,
  FormatJobResult,
  FormattingConflict,
  ImportJobResult,
  Job,
  JobProgress,
  ReferenceStyle,
} from "@/types/document";

export type OnProgress = (progress: JobProgress) => void;

export async function getJob(id: string): Promise<Job> {
  return jsonOrThrow(await apiFetch(`/api/jobs/${encodeURIComponent(id)}`, { cache: "no-store" }), "Couldn't check on the job");
}

/** The user's latest jobs, newest first (e.g. recent exports: type "export", status "succeeded"). */
export async function listJobs(params: { type?: Job["type"]; status?: Job["status"]; limit?: number } = {}): Promise<Job[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) query.set(key, String(value));
  return jsonOrThrow(await apiFetch(`/api/jobs?${query}`, { cache: "no-store" }), "Couldn't load recent activity");
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
  const done = await startJob("/api/jobs/import-text", jsonInit("POST", { text, title }), "Failed to create document", onProgress);
  return getDocument(resultOf<ImportJobResult>(done).documentId);
}

/** An uploaded .docx/.pdf/.txt into a new document: uploaded, then read in a background job. */
export async function importFile(file: File, title?: string, onProgress?: OnProgress): Promise<Document> {
  onProgress?.({ stage: "uploading", progress: 0 });
  const formData = new FormData();
  formData.append("file", file);
  if (title) formData.append("title", title);
  // No manual Content-Type here -- the browser sets the multipart boundary itself.
  const done = await startJob("/api/jobs/import-file", { method: "POST", body: formData }, "Failed to upload document", onProgress);
  return getDocument(resultOf<ImportJobResult>(done).documentId);
}

/** Format by Example: reads the look of a reference .docx. Saves nothing; pass
 * its styleSystem to createTemplate to keep it. */
export async function extractReferenceStyle(file: File, onProgress?: OnProgress): Promise<ReferenceStyle> {
  onProgress?.({ stage: "uploading", progress: 0 });
  const formData = new FormData();
  formData.append("file", file);
  const done = await startJob("/api/jobs/extract-reference", { method: "POST", body: formData }, "Couldn't read the reference document", onProgress);
  return resultOf<ReferenceStyle>(done);
}

export type ExportOptions = { includeHeaders: boolean; includePageNumbers: boolean; includePageBreaks: boolean };

/** A DOCX or PDF rendered in a background job; download it from jobFileUrl(job.id). */
export async function exportDocument(documentId: string, format: "docx" | "pdf", options: ExportOptions, onProgress?: OnProgress): Promise<Job & { result: ExportJobResult }> {
  const done = await startJob("/api/jobs/export", jsonInit("POST", { documentId, format, ...options }), "Failed to export", onProgress);
  return { ...done, result: resultOf<ExportJobResult>(done) };
}

export function jobFileUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}/file`;
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
  return documentWrite(documentId, "/api/jobs/format", { method: "POST", body: formData }, async (res) => {
    const done = await waitForJob(await jsonOrThrow<Job>(res, "Failed to apply formatting"), options.onProgress);
    const result = resultOf<FormatJobResult>(done);
    if (result.status === "conflicts") return { status: "conflicts", conflicts: result.conflicts };
    return {
      status: "applied",
      document: await getDocument(documentId),
      aiUnavailable: result.aiUnavailable,
      instructionEditCount: result.instructionEditCount,
    };
  });
}
