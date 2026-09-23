import { useEffect, useState } from "react";

import { formatDocument, listTemplates, redoFormatting, undoFormatting } from "@/services/api";
import type { ConflictResolution, Document, FormattingConflict, TemplateSummary } from "@/types/document";

export type FormattingNotice = { kind: "success" | "warning"; text: string };

/**
 * Templates and Instructions render as two separate rail panels (matching
 * the master-prompt screenshot's separate "Шаблони"/"Инструкции" icons),
 * but `/format` takes both in one call and `apply_formatting` REPLACES
 * `document.templateId` unconditionally -- submitting instructions alone
 * with no templateId would silently clear whatever template is already
 * applied. Lifting this state up to one shared hook (called once in
 * DocumentEditor) instead of duplicating it per-panel is what keeps that
 * correct: both panels read/write the same templateId, and either one's
 * "Apply" always sends the current value of both.
 */
export function useFormattingState(document: Document, onFormatted: (updated: Document) => void, onBeforeMutate: () => Promise<unknown>) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateId, setTemplateId] = useState(document.templateId ?? "");
  const [instructionsText, setInstructionsText] = useState("");
  const [instructionsFile, setInstructionsFile] = useState<File | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [isHistoryPending, setIsHistoryPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<FormattingNotice | null>(null);
  const [conflicts, setConflicts] = useState<FormattingConflict[] | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setError("Could not load templates. Is the backend running on port 8000?"));
  }, []);

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

  async function handleApply(resolutions?: ConflictResolution[]) {
    setError(null);
    setNotice(null);
    setIsApplying(true);
    const hadInstructions = Boolean(instructionsText.trim() || instructionsFile);
    try {
      if (!resolutions) await onBeforeMutate();
      const result = await formatDocument(document.id, {
        templateId: templateId || undefined,
        instructionsText: instructionsText.trim() || undefined,
        instructionsFile: instructionsFile ?? undefined,
        resolutions,
      });
      if (result.status === "conflicts") {
        setConflicts(result.conflicts);
        return;
      }
      setConflicts(null);
      onFormatted(result.document);
      setNotice(noticeForResult(hadInstructions, result.aiUnavailable, result.instructionEditCount));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply formatting.");
    } finally {
      setIsApplying(false);
    }
  }

  async function handleUndo() {
    setError(null);
    setNotice(null);
    setIsHistoryPending(true);
    try {
      await onBeforeMutate();
      onFormatted(await undoFormatting(document.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing to undo.");
    } finally {
      setIsHistoryPending(false);
    }
  }

  async function handleRedo() {
    setError(null);
    setNotice(null);
    setIsHistoryPending(true);
    try {
      await onBeforeMutate();
      onFormatted(await redoFormatting(document.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing to redo.");
    } finally {
      setIsHistoryPending(false);
    }
  }

  return {
    templates,
    templateId,
    setTemplateId,
    instructionsText,
    setInstructionsText,
    instructionsFile,
    setInstructionsFile,
    isApplying,
    isHistoryPending,
    error,
    notice,
    conflicts,
    setConflicts,
    handleApply,
    handleUndo,
    handleRedo,
  };
}

export type FormattingState = ReturnType<typeof useFormattingState>;
