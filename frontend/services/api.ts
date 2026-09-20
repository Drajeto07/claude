import type { ConflictResolution, Document, FormattingConflict, FormattingProperty, TemplateSummary } from "@/types/document";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function createDocument(text: string, title?: string): Promise<Document> {
  const res = await fetch(`${API_BASE_URL}/api/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  if (!res.ok) throw new Error(`Failed to create document (${res.status})`);
  return res.json();
}

export async function getDocument(id: string): Promise<Document> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch document (${res.status})`);
  return res.json();
}

export async function uploadDocument(file: File, title?: string): Promise<Document> {
  const formData = new FormData();
  formData.append("file", file);
  if (title) formData.append("title", title);

  // No manual Content-Type here -- the browser sets the multipart boundary itself.
  const res = await fetch(`${API_BASE_URL}/api/documents/upload`, { method: "POST", body: formData });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to upload document (${res.status})`);
  }
  return res.json();
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  const res = await fetch(`${API_BASE_URL}/api/templates`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch templates (${res.status})`);
  return res.json();
}

export async function createTemplate(input: {
  name: string;
  category: string;
  description?: string;
  rules: { target: string; property: FormattingProperty; value: string; unit?: string | null }[];
}): Promise<TemplateSummary> {
  const res = await fetch(`${API_BASE_URL}/api/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to create template (${res.status})`);
  }
  return res.json();
}

export type FormatResult = { status: "applied"; document: Document } | { status: "conflicts"; conflicts: FormattingConflict[] };

export async function formatDocument(
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

  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/format`, { method: "POST", body: formData });
  if (res.status === 409) {
    const body = await res.json();
    return { status: "conflicts", conflicts: body.detail.conflicts as FormattingConflict[] };
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to apply formatting (${res.status})`);
  }
  return { status: "applied", document: await res.json() };
}

export async function undoFormatting(documentId: string): Promise<Document> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/undo`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Nothing to undo (${res.status})`);
  }
  return res.json();
}

export async function redoFormatting(documentId: string): Promise<Document> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/redo`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Nothing to redo (${res.status})`);
  }
  return res.json();
}

export async function setElementStyle(
  documentId: string,
  elementId: string,
  input: { property: FormattingProperty; value: string; unit?: string | null },
): Promise<Document> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/elements/${elementId}/style`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to set style (${res.status})`);
  }
  return res.json();
}

export async function clearElementStyle(
  documentId: string,
  elementId: string,
  property: FormattingProperty,
): Promise<Document> {
  const res = await fetch(`${API_BASE_URL}/api/documents/${documentId}/elements/${elementId}/style/${property}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to clear style (${res.status})`);
  }
  return res.json();
}
