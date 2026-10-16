"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileArchive, Languages, Loader2, Wand2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { languageName, LANGUAGES } from "@/editor/languages";
import { batchExport, batchFormat, batchTranslate, errorMessage, getBatch, jobFileUrl } from "@/services/api";
import { queryKeys, useTemplates } from "@/services/queries";
import type { Batch, ExportJobResult, Job } from "@/types/document";

/**
 * What can be done to the documents ticked in the list at once (brief §61): one template applied
 * to all of them, as a batch of format jobs followed here until each is done (FEAT-001) -- a
 * document the template's rules conflict with is to open and resolve on its own -- or all of them
 * exported into one ZIP, each file read back and checked (FEAT-002), or translated into one
 * language, a new document each, the originals untouched (FEAT-003).
 */
export function BatchBar({ selected, onClear }: { selected: string[]; onClear: () => void }) {
  const queryClient = useQueryClient();
  const { data: templates } = useTemplates();
  const [templateId, setTemplateId] = useState("");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchKind, setBatchKind] = useState<"format" | "translate">("format");
  const [language, setLanguage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [format, setFormat] = useState<"docx" | "pdf">("docx");
  const [exporting, setExporting] = useState<number | null>(null); // progress, while the ZIP is made
  const [exported, setExported] = useState<(Job & { result: ExportJobResult }) | null>(null);

  async function exportAll() {
    setExporting(0);
    setError(null);
    setExported(null);
    try {
      setExported(await batchExport(selected, format, ({ progress }) => setExporting(progress)));
    } catch (err) {
      setError(errorMessage(err, "Couldn't export the documents."));
    } finally {
      setExporting(null);
    }
  }
  const { data: batch } = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => getBatch(batchId!),
    enabled: batchId !== null,
    refetchInterval: (query) => {
      const current = query.state.data as Batch | undefined;
      return current && current.done >= current.total ? false : 1000;
    },
  });
  const finished = batch !== undefined && batch.done >= batch.total;
  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ queryKey: queryKeys.allDocumentLists }); // their status: formatted
  }, [finished, queryClient]);

  async function apply() {
    setStarting(true);
    setError(null);
    try {
      setBatchKind("format");
      setBatchId((await batchFormat(selected, templateId)).id);
    } catch (err) {
      setError(errorMessage(err, "Couldn't start formatting the documents."));
    } finally {
      setStarting(false);
    }
  }

  async function translateAll() {
    setStarting(true);
    setError(null);
    try {
      setBatchKind("translate");
      setBatchId((await batchTranslate(selected, language)).id);
    } catch (err) {
      setError(errorMessage(err, "Couldn't start translating the documents."));
    } finally {
      setStarting(false);
    }
  }
  const busy = starting || (batchId !== null && !finished);
  const translations = batchKind === "translate" && batch ? batch.jobs.filter((job) => job.status === "succeeded" && job.result && "documentId" in job.result) : [];

  return (
    <section aria-label="Selected documents" className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-sm">
      <span className="font-medium text-zinc-800 dark:text-zinc-200">
        {selected.length} selected
      </span>
      <label className="flex items-center gap-2 text-zinc-600 dark:text-zinc-400">
        Template
        <select
          value={templateId}
          onChange={(event) => setTemplateId(event.target.value)}
          className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        >
          <option value="">Choose…</option>
          {(templates ?? []).map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={() => void apply()}
        disabled={!templateId || busy}
        className="flex items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
      >
        <Wand2 className="h-3.5 w-3.5" aria-hidden="true" />
        Apply to {selected.length} document{selected.length === 1 ? "" : "s"}
      </button>
      <span className="flex items-center gap-2">
        <select
          aria-label="Translate into"
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
          className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        >
          <option value="">Translate into…</option>
          {LANGUAGES.map((option) => (
            <option key={option.tag} value={option.tag}>
              {option.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void translateAll()}
          disabled={!language || busy}
          className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          <Languages className="h-3.5 w-3.5" aria-hidden="true" />
          Translate {selected.length} document{selected.length === 1 ? "" : "s"}
        </button>
      </span>
      <span className="flex items-center gap-2">
        <select
          aria-label="Export format"
          value={format}
          onChange={(event) => setFormat(event.target.value as "docx" | "pdf")}
          className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
        >
          <option value="docx">Word</option>
          <option value="pdf">PDF</option>
        </select>
        <button
          type="button"
          onClick={() => void exportAll()}
          disabled={exporting !== null}
          className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          <FileArchive className="h-3.5 w-3.5" aria-hidden="true" />
          {exporting !== null ? `Exporting… ${exporting}%` : "Export as ZIP"}
        </button>
      </span>
      <button type="button" onClick={onClear} className="ml-auto flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        <X className="h-3.5 w-3.5" aria-hidden="true" /> Clear selection
      </button>
      {batch && (
        <p role="status" className="basis-full text-xs text-zinc-700 dark:text-zinc-300">
          {!finished && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {batch.done} of {batch.total} {batchKind === "translate" ? `translated into ${languageName(language)}` : "done"}
          {batch.conflicts > 0 && `; ${batch.conflicts} with conflicts to resolve (open each to choose)`}
          {batch.failed > 0 && `; ${batch.failed} failed`}.
          {translations.length > 0 && (
            <span className="ml-1">
              New documents, the originals as they were:{" "}
              {translations.map((job, index) => (
                <Link key={job.id} href={`/documents/${(job.result as { documentId: string }).documentId}`} className="ml-1 font-medium text-accent hover:underline">
                  translation {index + 1}
                </Link>
              ))}
            </span>
          )}
        </p>
      )}
      {exported && (
        <p className="basis-full text-xs text-zinc-700 dark:text-zinc-300">
          <a href={jobFileUrl(exported.id)} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
            <Download className="h-3.5 w-3.5" aria-hidden="true" /> {exported.result.filename}
          </a>{" "}
          {describeParts(exported.result)}
        </p>
      )}
      {error && (
        <p role="alert" className="basis-full text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}

/** What a batch export holds: every file checked, or which weren't, or went missing. */
function describeParts(result: ExportJobResult): string {
  const parts = result.parts ?? [];
  const missing = parts.filter((part) => part.missing).length;
  const unchecked = parts.filter((part) => !part.missing && !part.verified).length;
  const kept = parts.length - missing;
  return [
    `${kept} file${kept === 1 ? "" : "s"}`,
    unchecked ? `${unchecked} not holding every word of its document (open it to see why)` : "each holding every word of its document",
    missing ? `${missing} deleted meanwhile, left out` : null,
  ]
    .filter(Boolean)
    .join("; ");
}
