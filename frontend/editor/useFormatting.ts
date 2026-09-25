"use client";

import { useState } from "react";

import { errorMessage, formatDocument } from "@/services/api";
import { useInvalidateTemplates, useTemplates } from "@/services/queries";
import type { ConflictResolution, Document, FormattingConflict, JobProgress, Template } from "@/types/document";

export type FormattingNotice = { kind: "success" | "warning"; text: string };

/** Where a formatting run was started: only that place shows its progress. */
export type ApplyOrigin = "templates" | "instructions" | "reference" | "quick" | "conflicts";

const NO_TEMPLATES: Template[] = [];

function noticeForResult(hadInstructions: boolean, aiUnavailable: boolean, instructionEditCount: number): FormattingNotice | null {
  if (!hadInstructions) return null;
  if (aiUnavailable) {
    return {
      kind: "warning",
      text: "AI instructions aren't available right now (no API key configured on the server) -- only the template, if any, was applied.",
    };
  }
  if (instructionEditCount === 0) {
    return {
      kind: "warning",
      text: "Your instructions didn't produce any change -- try naming a specific element or property, e.g. “make the title bold”.",
    };
  }
  return { kind: "success", text: `Applied ${instructionEditCount} change${instructionEditCount === 1 ? "" : "s"} from your instructions.` };
}

/**
 * Applying a template and/or instructions (a formatting job). Templates and
 * Instructions are two separate panels, but one formatting call takes both and
 * replaces the document's template -- instructions sent alone would clear the
 * template applied. So this state lives once, in the editor shell, and either
 * panel's "Apply" sends the current value of both.
 *
 * `apply` shows the formatted document; `flush` saves pending typing first.
 */
export function useFormatting(document: Document, apply: (updated: Document) => void, flush: () => Promise<unknown>) {
  const { data: templatesData } = useTemplates();
  const invalidateTemplates = useInvalidateTemplates();
  const templates = templatesData ?? NO_TEMPLATES;
  const [selectedTemplateId, setTemplateId] = useState(document.templateId ?? "");
  const [instructionsText, setInstructionsText] = useState("");
  const [instructionsFile, setInstructionsFile] = useState<File | null>(null);
  const [applyingFrom, setApplyingFrom] = useState<ApplyOrigin | null>(null);
  // The formatting job's real stage and percentage while it runs.
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<FormattingNotice | null>(null);
  const [conflicts, setConflicts] = useState<FormattingConflict[] | null>(null);

  // A template deleted (or no longer shared) since it was applied counts as
  // none, so "Apply" never sends an id the server would reject. Until the list
  // has loaded, the document's own value stands.
  const templateId =
    templatesData === undefined || selectedTemplateId === "" || templates.some((template) => template.id === selectedTemplateId)
      ? selectedTemplateId
      : "";

  /** `options.templateId`/`options.instructionsText`: a template just created, or
   * instructions just typed elsewhere (the quick bar), not in this render's state yet. */
  async function handleApply(
    origin: ApplyOrigin,
    options: { resolutions?: ConflictResolution[]; templateId?: string; instructionsText?: string } = {},
  ) {
    const instructions = (options.instructionsText ?? instructionsText).trim();
    setError(null);
    setNotice(null);
    setApplyingFrom(origin);
    setProgress({ stage: "queued", progress: 0 });
    try {
      await flush();
      const result = await formatDocument(document.id, {
        templateId: (options.templateId ?? templateId) || undefined,
        instructionsText: instructions || undefined,
        instructionsFile: instructionsFile ?? undefined,
        resolutions: options.resolutions,
        onProgress: setProgress,
      });
      if (result.status === "conflicts") {
        setConflicts(result.conflicts);
        return;
      }
      setConflicts(null);
      apply(result.document);
      setNotice(noticeForResult(Boolean(instructions || instructionsFile), result.aiUnavailable, result.instructionEditCount));
    } catch (err) {
      setError(errorMessage(err, "Could not apply formatting."));
    } finally {
      setApplyingFrom(null);
      setProgress(null);
    }
  }

  /** Selects a template that was just created (Format by Example) and formats with it. */
  async function applyTemplate(id: string) {
    await invalidateTemplates();
    setTemplateId(id);
    await handleApply("reference", { templateId: id });
  }

  return {
    templates,
    refreshTemplates: () => invalidateTemplates(),
    templateId,
    setTemplateId,
    instructionsText,
    setInstructionsText,
    instructionsFile,
    setInstructionsFile,
    isApplying: applyingFrom !== null,
    applyingFrom,
    progress,
    error,
    notice,
    conflicts,
    setConflicts,
    handleApply,
    applyTemplate,
  };
}

export type FormattingState = ReturnType<typeof useFormatting>;
