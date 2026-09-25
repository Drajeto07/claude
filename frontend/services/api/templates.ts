import { apiFetch, ApiError, errorFrom, jsonInit, jsonOrThrow, okOrThrow } from "@/services/api/client";
import type { CreatedTemplate, StylePreview, StyleSystem, Template, TemplateVersion, TemplateVisibility } from "@/types/document";

export class TemplateConflictError extends ApiError {
  constructor(requestId: string | null = null) {
    const message = "This template was changed in another tab or by someone else, so your edit wasn't saved.";
    super(412, { code: "template_version_conflict", message }, message, requestId);
    this.name = "TemplateConflictError";
  }
}

// Template writes carry the version they started from; a 412 means it moved on.
async function templateOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (res.status === 412) throw new TemplateConflictError((await errorFrom(res, fallback)).requestId);
  return jsonOrThrow<T>(res, fallback);
}

const templatePath = (id: string, rest = "") => `/api/templates/${encodeURIComponent(id)}${rest}`;

export async function listTemplates(): Promise<Template[]> {
  return jsonOrThrow(await apiFetch("/api/templates", { cache: "no-store" }), "Failed to fetch templates");
}

export async function getTemplate(id: string): Promise<Template> {
  return jsonOrThrow(await apiFetch(templatePath(id), { cache: "no-store" }), "Failed to load the template");
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
  return templateOrThrow(await apiFetch(templatePath(id), jsonInit("PUT", changes, version)), "Failed to save the template");
}

export async function deleteTemplate(id: string): Promise<void> {
  await okOrThrow(await apiFetch(templatePath(id), { method: "DELETE" }), "Failed to delete the template");
}

export async function duplicateTemplate(id: string, name?: string): Promise<Template> {
  return jsonOrThrow(await apiFetch(templatePath(id, "/duplicate"), jsonInit("POST", name ? { name } : {})), "Failed to duplicate the template");
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
  return jsonOrThrow(await apiFetch(templatePath(id, "/versions"), { cache: "no-store" }), "Failed to load the history");
}

export async function restoreTemplateVersion(id: string, number: number, version: number | null): Promise<Template> {
  return templateOrThrow(await apiFetch(templatePath(id, `/versions/${number}/restore`), jsonInit("POST", {}, version)), "Failed to restore that version");
}

/** How a document would look under an unsaved style system, resolved by the real engine. */
export async function previewStyleSystem(styleSystem: StyleSystem, signal?: AbortSignal): Promise<StylePreview> {
  return jsonOrThrow(await apiFetch("/api/templates/preview", { ...jsonInit("POST", styleSystem), signal }), "Failed to preview");
}
