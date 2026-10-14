"use client";

import { ArrowRightLeft, Check, Eye, Languages, Minus, Plus, Wrench, X } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { languageName } from "@/editor/languages";
import { selectElementById } from "@/editor/useSelection";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { acceptProposal, errorMessage, rejectProposal } from "@/services/api";
import type { Document, ProposedChange } from "@/types/document";

type Words = Messages["edPanels"]["proposals"];

const KIND: Record<ProposedChange["type"], { icon: typeof Plus; className: string }> = {
  delete_element: { icon: Minus, className: "text-danger" },
  insert_element: { icon: Plus, className: "text-success" },
  move_element: { icon: ArrowRightLeft, className: "text-sky-700 dark:text-sky-400" },
  replace_content: { icon: Languages, className: "text-accent" },
};

function short(text: string | null | undefined, limit = 80): string {
  const plain = (text ?? "").split(/\s+/).filter(Boolean).join(" ");
  return plain.length > limit ? `${plain.slice(0, limit)}…` : plain;
}

/** The element's text as it is now -- what accepting would remove or move. */
function liveText(document: Document, elementId: string | null | undefined): string | null {
  const element = elementId ? document.elements.find((candidate) => candidate.id === elementId) : undefined;
  return element ? element.content : null;
}

function where(document: Document, proposal: ProposedChange, t: Words): string {
  if (!proposal.afterElementId) return t.atStart;
  const after = liveText(document, proposal.afterElementId);
  return after ? format(t.after, { text: short(after, 40) }) : t.afterGone;
}

/** Where a change came from, for a list that mixes them (the Review panel). */
function SourceTag({ proposal }: { proposal: ProposedChange }) {
  const t = useI18n().m.edPanels.proposals;
  return <span className="mb-1 inline-block rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted">{t.sources[proposal.source]}</span>;
}

/** One waiting change: what it does and to what, before anything happens, with Accept / Reject / Show. */
export function ProposalCard({ proposal, busy, onAccept, onReject, onShow, showSource = false }: {
  proposal: ProposedChange;
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
  onShow: (elementId: string) => void;
  showSource?: boolean;
}) {
  const { document } = useDocumentEditor();
  const { m } = useI18n();
  const t = m.edPanels.proposals;
  const verb = t.verbs[proposal.type];
  const kind = KIND[proposal.type];
  const Icon = kind.icon;
  const target = proposal.type === "insert_element" ? proposal.afterElementId : proposal.elementId;
  const text = proposal.type === "insert_element" ? proposal.after : (liveText(document, proposal.elementId) ?? proposal.before);
  const what =
    proposal.type === "insert_element"
      ? format(t.insert, { verb, type: proposal.elementType ?? t.paragraph, where: where(document, proposal, t) })
      : proposal.type === "move_element"
        ? format(t.move, { verb, where: where(document, proposal, t) })
        : proposal.type === "replace_content"
          ? format(t.translate, { verb, language: languageName(proposal.targetLanguage) })
          : format(t.other, { verb });
  const healthFix = proposal.source === "health";
  const translation = proposal.type === "replace_content" && !healthFix;
  const textChanges = healthFix && proposal.type === "replace_content" && (proposal.after ?? "") !== (proposal.before ?? "");

  if (healthFix) {
    return (
      <li className="rounded-lg border border-line p-2.5">
        {showSource && <SourceTag proposal={proposal} />}
        <p className="flex items-start gap-1.5 text-sm font-medium text-success">
          <Wrench className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {proposal.reason}
        </p>
        {textChanges ? (
          <div className="mt-1 grid gap-1.5 text-sm">
            <p className="whitespace-pre-wrap text-muted line-through decoration-red-500/70"><span className="block text-[11px] uppercase tracking-wide no-underline">{t.nowLabel}</span>{short(proposal.before, 300)}</p>
            <p className="whitespace-pre-wrap text-foreground"><span className="block text-[11px] uppercase tracking-wide text-muted">{t.fixed}</span>{short(proposal.after, 300)}</p>
          </div>
        ) : (
          proposal.type === "delete_element" && proposal.before && <p className="mt-1 text-sm text-foreground line-through decoration-red-500/70">{short(proposal.before, 300)}</p>
        )}
        <Actions busy={busy} onAccept={onAccept} onReject={onReject} onShow={target ? () => onShow(target) : undefined} />
      </li>
    );
  }

  return (
    <li className="rounded-lg border border-line p-2.5">
      {showSource && <SourceTag proposal={proposal} />}
      <p className={`flex items-center gap-1.5 text-sm font-medium ${kind.className}`}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {what}
      </p>
      {translation ? (
        <div className="mt-1 grid gap-1.5 text-sm">
          <p className="whitespace-pre-wrap text-muted"><span className="block text-[11px] uppercase tracking-wide">{t.original}</span>{short(text, 400)}</p>
          <p className="whitespace-pre-wrap text-foreground"><span className="block text-[11px] uppercase tracking-wide text-muted">{t.translation}</span>{short(proposal.after, 400)}</p>
          {proposal.problems.length > 0 && (
            <ul className="list-disc pl-4 text-xs text-warning">
              {proposal.problems.map((problem) => (
                <li key={problem}>{format(m.edPanels.common.leftAsItWas, { reason: problem })}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className={`mt-1 whitespace-pre-wrap text-sm text-foreground ${proposal.type === "delete_element" ? "line-through decoration-red-500/70" : ""}`}>
          {short(text, 400)}
        </p>
      )}
      {proposal.reason && <p className="mt-1 truncate text-xs text-muted" title={proposal.reason}>{translation ? proposal.reason : format(t.from, { reason: proposal.reason })}</p>}
      <Actions busy={busy} onAccept={onAccept} onReject={onReject} onShow={target ? () => onShow(target) : undefined} />
    </li>
  );
}

function Actions({ busy, onAccept, onReject, onShow }: { busy: boolean; onAccept: () => void; onReject: () => void; onShow?: () => void }) {
  const { m } = useI18n();
  const t = m.edPanels.proposals;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      <button type="button" onClick={onAccept} disabled={busy} className="flex items-center gap-1 rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50">
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
        {t.accept}
      </button>
      <button type="button" onClick={onReject} disabled={busy} className="flex items-center gap-1 rounded-full border border-line-strong px-3 py-1 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50">
        <X className="h-3.5 w-3.5" aria-hidden="true" />
        {t.reject}
      </button>
      {onShow && (
        <button type="button" onClick={onShow} className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-accent">
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          {m.edPanels.common.show}
        </button>
      )}
    </div>
  );
}

/**
 * Changes to the text an AI instruction asked for (brief §19, tracker AI-007):
 * each shown before anything happens -- what would be deleted (as it reads now),
 * added or moved, and where -- and applied only when accepted. A rejected one
 * is simply gone; an accepted one is an ordinary, undoable change.
 */
/** Accepting, rejecting and showing waiting changes, one at a time; `run` does any other change the same way. */
export function useProposalActions() {
  const { editor, change } = useDocumentEditor();
  const failed = useI18n().m.edPanels.proposals.failed;
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(key: string, action: (documentId: string) => Promise<Document>) {
    setBusy(key);
    setError(null);
    try {
      await change(action);
    } catch (err) {
      setError(errorMessage(err, failed));
    } finally {
      setBusy(null);
    }
  }

  function show(elementId: string) {
    if (!editor || editor.isDestroyed) return;
    selectElementById(editor, elementId);
    editor.view.dom.querySelector(`[data-element-id="${CSS.escape(elementId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  return {
    busy,
    error,
    run,
    accept: (proposalId: string) => run(proposalId, (documentId) => acceptProposal(documentId, proposalId)),
    reject: (proposalId: string) => run(proposalId, (documentId) => rejectProposal(documentId, proposalId)),
    show,
  };
}

export function ProposalsList({ source }: { source?: ProposedChange["source"] } = {}) {
  const { document } = useDocumentEditor();
  const t = useI18n().m.edPanels.proposals;
  const { busy, error, accept, reject, show } = useProposalActions();
  const proposals = (document.proposals ?? []).filter((proposal) => !source || proposal.source === source);
  if (proposals.length === 0) return null;

  return (
    <section aria-label={t.title} className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{format(t.heading, { count: proposals.length })}</h3>
      <p className="text-xs text-muted">
        {source === "translation" ? t.fromTranslation : source === "health" ? t.fromHealth : t.fromInstruction} {t.nothingUntil}
      </p>
      <ul className="flex flex-col gap-2">
        {proposals.map((proposal) => (
          <ProposalCard
            key={proposal.id}
            proposal={proposal}
            busy={busy !== null}
            onAccept={() => void accept(proposal.id)}
            onReject={() => void reject(proposal.id)}
            onShow={show}
          />
        ))}
      </ul>
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}
