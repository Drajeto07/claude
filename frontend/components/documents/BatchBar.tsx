"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileArchive, Languages, Loader2, Wand2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { templateText } from "@/components/templates/templateText";
import { LANGUAGES } from "@/editor/languages";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural, type Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { batchExport, batchFormat, batchTranslate, errorMessage, getBatch, jobFileUrl } from "@/services/api";
import { queryKeys, useTemplates } from "@/services/queries";
import type { Batch, ExportJobResult, Job } from "@/types/document";

const select = "h-8 rounded-lg border border-line bg-surface px-2 text-sm text-foreground focus:border-accent focus:outline-none";
const quiet = "flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50";

/** A language's name in the interface language ("Bulgarian" / "български"). */
function languageLabel(tag: string, locale: Locale, fallback: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "language" }).of(tag) ?? fallback;
  } catch {
    return fallback;
  }
}

/**
 * What can be done to the documents ticked in the list at once (brief §61): one template applied
 * to all of them, as a batch of format jobs followed here until each is done (FEAT-001) -- a
 * document the template's rules conflict with is to open and resolve on its own -- or all of them
 * exported into one ZIP, each file read back and checked (FEAT-002), or translated into one
 * language, a new document each, the originals untouched (FEAT-003).
 */
export function BatchBar({ selected, onClear }: { selected: string[]; onClear: () => void }) {
  const { m, locale } = useI18n();
  const t = m.documents.batch;
  const queryClient = useQueryClient();
  const { data: templates } = useTemplates();
  const [templateId, setTemplateId] = useState("");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchKind, setBatchKind] = useState<"format" | "translate">("format");
  const [language, setLanguage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [fileFormat, setFileFormat] = useState<"docx" | "pdf">("docx");
  const [exporting, setExporting] = useState<number | null>(null); // progress, while the ZIP is made
  const [exported, setExported] = useState<(Job & { result: ExportJobResult }) | null>(null);

  async function exportAll() {
    setExporting(0);
    setError(null);
    setExported(null);
    try {
      setExported(await batchExport(selected, fileFormat, ({ progress }) => setExporting(progress)));
    } catch (err) {
      setError(errorMessage(err, t.exportFailed));
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
      setError(errorMessage(err, t.formatFailed));
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
      setError(errorMessage(err, t.translateFailed));
    } finally {
      setStarting(false);
    }
  }
  const busy = starting || (batchId !== null && !finished);
  const translations = batchKind === "translate" && batch ? batch.jobs.filter((job) => job.status === "succeeded" && job.result && "documentId" in job.result) : [];
  const languageName = (tag: string) => languageLabel(tag, locale, LANGUAGES.find((option) => option.tag === tag)?.name ?? tag);

  return (
    <section aria-label={t.region} className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-accent/30 bg-accent-soft px-4 py-3 text-sm">
      <span className="font-medium text-foreground">{format(t.selected, { count: selected.length })}</span>
      <label className="flex items-center gap-2 text-muted">
        {t.template}
        <select value={templateId} onChange={(event) => setTemplateId(event.target.value)} className={select}>
          <option value="">{t.choose}</option>
          {(templates ?? []).map((template) => (
            <option key={template.id} value={template.id}>
              {templateText(template, m).name}
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
        {plural(selected.length, t.apply)}
      </button>
      <span className="flex items-center gap-2">
        <select aria-label={t.translateInto} value={language} onChange={(event) => setLanguage(event.target.value)} className={select}>
          <option value="">{t.translateIntoPlaceholder}</option>
          {LANGUAGES.map((option) => (
            <option key={option.tag} value={option.tag}>
              {languageName(option.tag)}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => void translateAll()} disabled={!language || busy} className={quiet}>
          <Languages className="h-3.5 w-3.5" aria-hidden="true" />
          {plural(selected.length, t.translate)}
        </button>
      </span>
      <span className="flex items-center gap-2">
        <select aria-label={t.exportFormat} value={fileFormat} onChange={(event) => setFileFormat(event.target.value as "docx" | "pdf")} className={select}>
          <option value="docx">Word</option>
          <option value="pdf">PDF</option>
        </select>
        <button type="button" onClick={() => void exportAll()} disabled={exporting !== null} className={quiet}>
          <FileArchive className="h-3.5 w-3.5" aria-hidden="true" />
          {exporting !== null ? format(t.exporting, { progress: exporting }) : t.exportZip}
        </button>
      </span>
      <button type="button" onClick={onClear} className="ml-auto flex items-center gap-1 text-xs text-muted hover:text-foreground">
        <X className="h-3.5 w-3.5" aria-hidden="true" /> {t.clear}
      </button>
      {batch && (
        <p role="status" className="basis-full text-xs text-foreground">
          {!finished && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {batchKind === "translate"
            ? format(t.translatedOf, { done: batch.done, total: batch.total, language: languageName(language) })
            : format(t.doneOf, { done: batch.done, total: batch.total })}
          {batch.conflicts > 0 && format(t.conflicts, { count: batch.conflicts })}
          {batch.failed > 0 && format(t.failed, { count: batch.failed })}.
          {translations.length > 0 && (
            <span className="ml-1">
              {t.newDocuments}{" "}
              {translations.map((job, index) => (
                <Link key={job.id} href={`/documents/${(job.result as { documentId: string }).documentId}`} className="ml-1 font-medium text-accent hover:underline">
                  {format(t.translation, { n: index + 1 })}
                </Link>
              ))}
            </span>
          )}
        </p>
      )}
      {exported && (
        <p className="basis-full text-xs text-foreground">
          <a href={jobFileUrl(exported.id)} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
            <Download className="h-3.5 w-3.5" aria-hidden="true" /> {exported.result.filename}
          </a>{" "}
          {describeParts(exported.result, t)}
        </p>
      )}
      {error && (
        <p role="alert" className="basis-full text-xs text-danger">
          {error}
        </p>
      )}
    </section>
  );
}

/** What a batch export holds: every file checked, or which weren't, or went missing. */
function describeParts(result: ExportJobResult, t: Messages["documents"]["batch"]): string {
  const parts = result.parts ?? [];
  const missing = parts.filter((part) => part.missing).length;
  const unchecked = parts.filter((part) => !part.missing && !part.verified).length;
  const kept = parts.length - missing;
  return [plural(kept, t.files), unchecked ? format(t.unverified, { count: unchecked }) : t.allVerified, missing ? format(t.missing, { count: missing }) : null]
    .filter(Boolean)
    .join("; ");
}
