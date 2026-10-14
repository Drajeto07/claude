"use client";

import { Languages, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { languageName, LANGUAGES } from "@/editor/languages";
import { ProposalsList } from "@/editor/panels/ProposalsList";
import { translationTarget } from "@/editor/translationTarget";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import { errorMessage, getDocumentLanguage, setDocumentLanguage, setGlossary, translateBlocks, translateDocument } from "@/services/api";
import type { DocumentLanguage, GlossaryTerm, TranslateResponse } from "@/types/document";

/** The label the server also puts on every translation (English: what the tests and the server's text match). */
export const TRANSLATION_LABEL = "AI-assisted translation — review required.";

const selectClass =
  "w-full rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-foreground focus:border-accent focus:outline-none";
const buttonClass =
  "flex items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium disabled:opacity-50";

/** The glossary: terms and how they are translated; a locked one always so (TRAN-004). */
function Glossary() {
  const { document, change } = useDocumentEditor();
  const t = useI18n().m.edPanels.translate;
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
      setError(errorMessage(err, t.glossaryFailed));
    }
  }

  return (
    <section aria-label={t.glossary} className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t.glossary}</h3>
      {terms.map((term, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <input aria-label={format(t.termN, { number: index + 1 })} value={term.source} onChange={(e) => edit(index, { source: e.target.value })} placeholder={t.term} className={selectClass} />
          <input aria-label={format(t.translationN, { number: index + 1 })} value={term.target} onChange={(e) => edit(index, { target: e.target.value })} placeholder={t.translation} className={selectClass} />
          <label className="flex items-center gap-1 text-xs text-muted" title={t.lockedTitle}>
            <input type="checkbox" checked={term.locked} onChange={(e) => edit(index, { locked: e.target.checked })} />
            {t.locked}
          </label>
          <button type="button" aria-label={format(t.removeTerm, { number: index + 1 })} onClick={() => { setTerms((current) => current.filter((_, i) => i !== index)); setSaved(false); }} className="text-muted hover:text-danger">
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => { setTerms((current) => [...current, { source: "", target: "", domain: null, locked: true, caseSensitive: false, sourceLanguage: null, targetLanguage: null }]); setSaved(false); }}
          className={`${buttonClass} border border-line-strong text-foreground hover:bg-surface-muted`}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t.addTerm}
        </button>
        {!saved && (
          <button type="button" onClick={() => void save()} className={`${buttonClass} bg-accent text-accent-foreground hover:opacity-90`}>
            {t.saveGlossary}
          </button>
        )}
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

/**
 * The Translate rail panel (brief §51, §94; tracker TRAN-008): the document's language (detected,
 * or set), the language to translate into, and "Translate selection" -- proposals to review,
 * original against translation -- or "Create translated version", a new document beside this
 * one. Always marked as AI-assisted, never as certified.
 */
export function TranslatePanel() {
  const { document, editor, change, flush } = useDocumentEditor();
  const { m } = useI18n();
  const t = m.edPanels.translate;
  const common = m.edPanels.common;
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
      setError(errorMessage(err, t.setLanguageFailed));
    }
  }

  async function translateSelection() {
    const chosen = editor && !editor.isDestroyed ? translationTarget(editor) : null;
    if (!chosen) {
      setError(t.putCursor);
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
      setError(errorMessage(err, t.selectionFailed));
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
      setError(errorMessage(err, t.wholeFailed));
    } finally {
      setBusy(null);
      setProgress(null);
    }
  }

  const detected = language?.detected ? format(t.detected, { language: languageName(language.detected) }) : t.notDetected;
  return (
    <div className="flex flex-col gap-4">
      <p role="note" className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning ring-1 ring-warning/30">
        {t.label} {t.checked}
      </p>
      {document.metadata.translatedFrom && (
        <p className="text-xs text-muted">
          {format(t.translatedFrom, { title: document.metadata.translatedFrom.title, language: languageName(document.metadata.translatedFrom.targetLanguage) })}
        </p>
      )}
      <label className="flex flex-col gap-1 text-xs text-muted">
        {t.documentIn}
        <select aria-label={t.documentLanguage} value={source ?? ""} onChange={(e) => void chooseSource(e.target.value)} className={selectClass}>
          <option value="">{detected}</option>
          {LANGUAGES.map((option) => (
            <option key={option.tag} value={option.tag}>{option.name}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        {t.into}
        <select aria-label={t.into} value={target} onChange={(e) => setTarget(e.target.value)} className={selectClass}>
          {LANGUAGES.map((option) => (
            <option key={option.tag} value={option.tag}>{option.name}</option>
          ))}
        </select>
      </label>
      <div className="flex flex-col gap-2">
        <button type="button" onClick={() => void translateSelection()} disabled={busy !== null} className={`${buttonClass} bg-accent text-accent-foreground hover:opacity-90`}>
          <Languages className="h-4 w-4" aria-hidden="true" />
          {busy === "selection" ? t.translating : t.selection}
        </button>
        <button type="button" onClick={() => void translateWhole()} disabled={busy !== null} className={`${buttonClass} border border-line-strong text-foreground hover:bg-surface-muted`}>
          {busy === "document" ? format(t.translatingPercent, { percent: progress ?? 0 }) : t.whole}
        </button>
        <p className="text-xs text-muted">{t.newDocument}</p>
      </div>
      {result && (
        <div role="status" className="text-xs text-muted">
          {result.proposalCount > 0
            ? plural(result.proposalCount, t.blocks, { language: languageName(target) })
            : t.nothing}
          {result.notTranslated.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {result.notTranslated.map((item) => (
                <li key={item.elementId}>{format(common.leftAsItWas, { reason: item.reasons.join("; ") })}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <ProposalsList source="translation" />
      <Glossary />
    </div>
  );
}
