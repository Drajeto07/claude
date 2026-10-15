"use client";

import { AlertTriangle, CheckCircle2, Download, Loader2, ShieldCheck, Stethoscope, XCircle } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { ProposalsList } from "@/editor/panels/ProposalsList";
import { selectElementById } from "@/editor/useSelection";
import { useI18n } from "@/i18n/I18nProvider";
import { plural } from "@/i18n/locales";
import { doctorCheck, doctorDownload, doctorProposals, doctorReport, errorMessage } from "@/services/api";
import type { DoctorCheckResult, DoctorReport, DoctorWordRepair } from "@/types/document";

const button =
  "flex items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50";

/**
 * Document Doctor v0 (prototype, ?doctor=1): check the Word file, choose repairs, check the repaired file against
 * the original, download it only when verified. Nothing changes until the person chooses: repairs in the file are
 * ticked here, repairs in the editor are proposals accepted one by one (the same cards as the Review panel).
 */
export function DoctorPanel() {
  const { document, editor, flush, change } = useDocumentEditor();
  const { m } = useI18n();
  const t = m.doctor;
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<DoctorCheckResult | null>(null);
  const [busy, setBusy] = useState<"analyse" | "propose" | "check" | "download" | null>(null);
  const [proposed, setProposed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(what: typeof busy, fallback: string, action: () => Promise<T>): Promise<T | undefined> {
    setBusy(what);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(errorMessage(err, fallback));
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  async function analyse() {
    setResult(null);
    setProposed(false);
    const found = await run("analyse", t.analyseFailed, async () => {
      await flush();
      return doctorReport(document.id);
    });
    if (found) {
      setReport(found);
      setChosen(new Set());
    }
  }

  async function propose() {
    const done = await run("propose", t.proposeFailed, () => change(async (documentId) => (await doctorProposals(documentId)).document));
    if (done !== undefined) {
      setProposed(true);
      setResult(null);
    }
  }

  async function check() {
    const found = await run("check", t.checkFailed, async () => {
      await flush();
      return doctorCheck(document.id, [...chosen]);
    });
    if (found) setResult(found);
  }

  function show(elementId: string) {
    if (!editor || editor.isDestroyed) return;
    selectElementById(editor, elementId);
    editor.view.dom.querySelector(`[data-element-id="${CSS.escape(elementId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function label(repair: DoctorWordRepair): string {
    return repair.kind === "empty_paragraphs" ? plural(repair.blocks, t.kinds.empty_paragraphs) : t.kinds[repair.kind];
  }

  function toggle(id: string, on: boolean) {
    setChosen((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
    setResult(null);
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Stethoscope className="h-4 w-4 text-accent" aria-hidden="true" />
          <span>{t.title}</span>
          <span className="rounded-full bg-warning-soft px-1.5 py-0.5 text-[10px] font-medium text-warning">{t.prototype}</span>
        </p>
        <p className="mt-1 text-xs text-muted">{t.intro}</p>
      </div>

      <button type="button" onClick={() => void analyse()} disabled={busy !== null} className={`${button} bg-accent text-accent-foreground hover:opacity-90`}>
        {busy === "analyse" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
        {busy === "analyse" ? t.analysing : t.analyse}
      </button>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}

      {report && !report.available && (
        <section aria-label={t.refusedTitle} className="rounded-lg bg-warning-soft p-3 text-xs text-warning ring-1 ring-warning/30">
          <p className="flex items-center gap-1.5 font-semibold">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            {t.refusedTitle}
          </p>
          <p className="mt-1">{t.refusedIntro}</p>
          <ul className="mt-1 list-disc pl-4">
            {report.refusals.map((refusal) => (
              <li key={refusal.code}>{refusal.message}</li>
            ))}
          </ul>
        </section>
      )}

      {report && (
        <section aria-label={t.findings} className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t.findings}</h3>
          {report.findings.length === 0 && <p className="text-xs text-muted">{t.noFindings}</p>}
          <ul className="flex flex-col gap-2">
            {report.findings.map((finding) => (
              <li key={finding.checkId} className="rounded-lg border border-line p-2.5 text-xs">
                <p className="flex items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{finding.title}</span>
                  <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${finding.repair === "safe" ? "bg-success/10 text-success" : "bg-surface-muted text-muted"}`}>
                    {finding.repair === "safe" ? t.safe : t.review}
                  </span>
                </p>
                <p className="mt-0.5 text-muted">{finding.summary}</p>
                {finding.issues.map((issue) => (
                  <p key={issue.message} className="mt-1 text-muted">
                    {issue.message}
                    {issue.elementIds.slice(0, 3).map((elementId) => (
                      <button key={elementId} type="button" onClick={() => show(elementId)} className="ml-1.5 font-medium text-accent hover:underline">
                        {t.show}
                      </button>
                    ))}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}

      {report?.available && report.wordRepairs.length > 0 && (
        <section aria-label={t.fileRepairs} className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t.fileRepairs}</h3>
          <p className="text-xs text-muted">{t.fileRepairsIntro}</p>
          {report.wordRepairs.map((repair) => (
            <label key={repair.id} className="flex items-start gap-2 text-xs text-foreground">
              <input type="checkbox" checked={chosen.has(repair.id)} onChange={(event) => toggle(repair.id, event.target.checked)} className="mt-0.5 h-3.5 w-3.5 accent-[var(--accent)]" />
              <span>
                {label(repair)}
                <span className="block text-muted">{repair.where}</span>
              </span>
            </label>
          ))}
        </section>
      )}

      {report?.available && (report.modelRepairs > 0 || report.blockRefusals.length > 0) && (
        <section aria-label={t.editorRepairs} className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t.editorRepairs}</h3>
          {report.modelRepairs > 0 && !proposed && (
            <button type="button" onClick={() => void propose()} disabled={busy !== null} className={`${button} border border-line-strong text-foreground hover:bg-surface-muted`}>
              {busy === "propose" ? t.proposing : plural(report.modelRepairs, t.propose)}
            </button>
          )}
          {proposed && <p className="text-xs text-muted">{t.proposed}</p>}
          {report.blockRefusals.length > 0 && <p className="text-xs text-muted">{plural(report.blockRefusals.length, t.leftAlone)}</p>}
          <ProposalsList source="health" />
        </section>
      )}

      {report?.available && (
        <section aria-label={t.check} className="flex flex-col gap-2 border-t border-line pt-3">
          <button type="button" onClick={() => void check()} disabled={busy !== null} className={`${button} border border-accent text-accent hover:bg-accent-soft`}>
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            {busy === "check" ? t.checking : t.check}
          </button>
          {result && (
            <div role="status" className="flex flex-col gap-1.5 text-xs">
              <p className={`font-semibold ${result.verified ? "text-success" : "text-danger"}`}>{result.verified ? t.verified : t.notVerified}</p>
              <ul className="flex flex-col gap-1">
                {result.checks.map((entry) => (
                  <li key={entry.name} className="flex items-start gap-1.5">
                    {entry.passed ? <CheckCircle2 className="mt-px h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" /> : <XCircle className="mt-px h-3.5 w-3.5 shrink-0 text-danger" aria-hidden="true" />}
                    <span>
                      <span className="font-medium text-foreground">{t.checks[entry.name]}</span>
                      <span className="block text-muted">{entry.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
              {result.skipped.length > 0 && <p className="text-warning">{plural(result.skipped.length, t.skipped)}</p>}
              {result.verified && (
                <button
                  type="button"
                  onClick={() => void run("download", t.downloadFailed, () => doctorDownload(document.id, [...chosen]))}
                  disabled={busy !== null}
                  className={`${button} bg-accent text-accent-foreground hover:opacity-90`}
                >
                  <Download className="h-3.5 w-3.5" aria-hidden="true" />
                  {busy === "download" ? t.downloading : t.download}
                </button>
              )}
            </div>
          )}
        </section>
      )}

      <p className="text-[11px] text-muted">{t.limits}</p>
    </div>
  );
}
