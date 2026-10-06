"use client";

import { Languages, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { languageName, LANGUAGES } from "@/editor/languages";
import { ProposalsList } from "@/editor/panels/ProposalsList";
import { translationTarget } from "@/editor/translationTarget";
import { errorMessage, getDocumentLanguage, setDocumentLanguage, setGlossary, translateBlocks, translateDocument } from "@/services/api";
import type { DocumentLanguage, GlossaryTerm, TranslateResponse } from "@/types/document";

export const TRANSLATION_LABEL = "AI-assisted translation — review required.";

const selectClass =
  "w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const buttonClass =
  "flex items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium disabled:opacity-50";

/** The glossary: terms and how they are translated; a locked one always so (TRAN-004). */
function Glossary() {
  const { document, change } = useDocumentEditor();
  const [terms, setTerms] = useState<GlossaryTerm[]>(document.glossary ?? []);
  const [saved, setSaved] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function edit(index: number, patch: Partial<GlossaryTerm>) {
    setTerms((current) => current.map((term, i) => (i === index ? { ...term, ...patch } : term)));
    setSaved(false);
  }

  async function save() {
    setError(null);
    try {
      await change((documentId) => setGlossary(documentId, terms.filter((term) => term.source.trim() && term.target.trim())));
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err, "Couldn't save the glossary."));
    }
  }

  return (
    <section aria-label="Glossary" className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Glossary</h3>
      {terms.map((term, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <input aria-label={`Term ${index + 1}`} value={term.source} onChange={(e) => edit(index, { source: e.target.value })} placeholder="Term" className={selectClass} />
          <input aria-label={`Translation ${index + 1}`} value={term.target} onChange={(e) => edit(index, { target: e.target.value })} placeholder="Translation" className={selectClass} />
          <label className="flex items-center gap-1 text-xs text-zinc-600 dark:text-zinc-400" title="Always translated so">
            <input type="checkbox" checked={term.locked} onChange={(e) => edit(index, { locked: e.target.checked })} />
            Locked
          </label>
          <button type="button" aria-label={`Remove term ${index + 1}`} onClick={() => { setTerms((current) => current.filter((_, i) => i !== index)); setSaved(false); }} className="text-zinc-400 hover:text-red-600">
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => { setTerms((current) => [...current, { source: "", target: "", domain: null, locked: true, caseSensitive: false, sourceLanguage: null, targetLanguage: null }]); setSaved(false); }}
          className={`${buttonClass} border border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800`}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          Add a term
        </button>
        {!saved && (
          <button type="button" onClick={() => void save()} className={`${buttonClass} bg-accent text-accent-foreground hover:opacity-90`}>
            Save glossary
          </button>
        )}
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
    </section>
  );
}

/**
 * The "Превод" rail panel (brief §51, §94; tracker TRAN-008): the document's language (detected,
 * or set), the language to translate into, and "Translate selection" -- proposals to review,
 * original against translation -- or "Create translated version", a new document beside this
 * one. Always marked as AI-assisted, never as certified.
 */
export function TranslatePanel() {
  const { document, editor, change, flush } = useDocumentEditor();
  const router = useRouter();
  const [language, setLanguage] = useState<DocumentLanguage | null>(null);
  const [target, setTarget] = useState<string>(document.metadata.language?.startsWith("bg") ? "en" : "bg");
  const [busy, setBusy] = useState<"selection" | "document" | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<TranslateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getDocumentLanguage(document.id).then((found) => active && setLanguage(found)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [document.id, document.metadata.language]);

  const source = document.metadata.language ?? null;

  async function chooseSource(tag: string) {
    setError(null);
    try {
      await change((documentId) => setDocumentLanguage(documentId, tag || null));
    } catch (err) {
      setError(errorMessage(err, "Couldn't set the language."));
    }
  }

  async function translateSelection() {
    const chosen = editor && !editor.isDestroyed ? translationTarget(editor) : null;
    if (!chosen) {
      setError("Put the cursor in a block, or select the text to translate.");
      return;
    }
    setBusy("selection");
    setError(null);
    setResult(null);
    try {
      await flush?.();
      await change(async (documentId) => {
        const answer = await translateBlocks(documentId, { ...chosen, targetLanguage: target, sourceLanguage: source });
        setResult(answer);
        return answer.document;
      });
    } catch (err) {
      setError(errorMessage(err, "Couldn't translate that."));
    } finally {
      setBusy(null);
    }
  }

  async function translateWhole() {
    setBusy("document");
    setError(null);
    setProgress(0);
    try {
      await flush?.();
      const created = await translateDocument(document.id, target, source, (job) => setProgress(job.progress));
      router.push(`/documents/${created}`);
    } catch (err) {
      setError(errorMessage(err, "Couldn't translate the document."));
    } finally {
      setBusy(null);
      setProgress(null);
    }
  }

  const detected = language?.detected ? `${languageName(language.detected)} (detected)` : "Not detected";
  return (
    <div className="flex flex-col gap-4">
      <p role="note" className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-600/20 dark:bg-amber-950/40 dark:text-amber-300">
        {TRANSLATION_LABEL} Numbers, units, codes and glossary terms are checked; the meaning isn&apos;t.
      </p>
      {document.metadata.translatedFrom && (
        <p className="text-xs text-zinc-600 dark:text-zinc-400">
          Translated from “{document.metadata.translatedFrom.title}” into {languageName(document.metadata.translatedFrom.targetLanguage)}.
        </p>
      )}
      <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
        The document is in
        <select aria-label="The document's language" value={source ?? ""} onChange={(e) => void chooseSource(e.target.value)} className={selectClass}>
          <option value="">{detected}</option>
          {LANGUAGES.map((option) => (
            <option key={option.tag} value={option.tag}>{option.name}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
        Translate into
        <select aria-label="Translate into" value={target} onChange={(e) => setTarget(e.target.value)} className={selectClass}>
          {LANGUAGES.map((option) => (
            <option key={option.tag} value={option.tag}>{option.name}</option>
          ))}
        </select>
      </label>
      <div className="flex flex-col gap-2">
        <button type="button" onClick={() => void translateSelection()} disabled={busy !== null} className={`${buttonClass} bg-accent text-accent-foreground hover:opacity-90`}>
          <Languages className="h-4 w-4" aria-hidden="true" />
          {busy === "selection" ? "Translating…" : "Translate selection"}
        </button>
        <button type="button" onClick={() => void translateWhole()} disabled={busy !== null} className={`${buttonClass} border border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800`}>
          {busy === "document" ? `Translating… ${progress ?? 0}%` : "Create translated version"}
        </button>
        <p className="text-xs text-zinc-500">A translated version is a new document; this one stays as it is.</p>
      </div>
      {result && (
        <div role="status" className="text-xs text-zinc-600 dark:text-zinc-400">
          {result.proposalCount > 0
            ? `${result.proposalCount} block${result.proposalCount === 1 ? "" : "s"} translated into ${languageName(target)}: review below.`
            : "Nothing to review."}
          {result.notTranslated.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {result.notTranslated.map((item) => (
                <li key={item.elementId}>Left as it was: {item.reasons.join("; ")}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <ProposalsList source="translation" />
      <Glossary />
    </div>
  );
}
