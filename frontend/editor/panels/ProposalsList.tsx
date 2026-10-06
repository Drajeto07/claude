"use client";

import { ArrowRightLeft, Check, Eye, Languages, Minus, Plus, X } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { languageName } from "@/editor/languages";
import { selectElementById } from "@/editor/useSelection";
import { acceptProposal, errorMessage, rejectProposal } from "@/services/api";
import type { Document, ProposedChange } from "@/types/document";

const KIND: Record<ProposedChange["type"], { verb: string; icon: typeof Plus; className: string }> = {
  delete_element: { verb: "Delete", icon: Minus, className: "text-red-600 dark:text-red-400" },
  insert_element: { verb: "Add", icon: Plus, className: "text-green-700 dark:text-green-400" },
  move_element: { verb: "Move", icon: ArrowRightLeft, className: "text-sky-700 dark:text-sky-400" },
  replace_content: { verb: "Translate", icon: Languages, className: "text-indigo-700 dark:text-indigo-400" },
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

function where(document: Document, proposal: ProposedChange): string {
  if (!proposal.afterElementId) return "at the very start";
  const after = liveText(document, proposal.afterElementId);
  return after ? `after “${short(after, 40)}”` : "after a block that is gone";
}

function Proposal({ proposal, busy, onAccept, onReject, onShow }: {
  proposal: ProposedChange;
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
  onShow: (elementId: string) => void;
}) {
  const { document } = useDocumentEditor();
  const kind = KIND[proposal.type];
  const Icon = kind.icon;
  const target = proposal.type === "insert_element" ? proposal.afterElementId : proposal.elementId;
  const text = proposal.type === "insert_element" ? proposal.after : (liveText(document, proposal.elementId) ?? proposal.before);
  const what =
    proposal.type === "insert_element"
      ? `${kind.verb} a ${proposal.elementType ?? "paragraph"} ${where(document, proposal)}`
      : proposal.type === "move_element"
        ? `${kind.verb} a block ${where(document, proposal)}`
        : proposal.type === "replace_content"
          ? `${kind.verb} a block into ${languageName(proposal.targetLanguage)}`
          : `${kind.verb} a block`;
  const translation = proposal.type === "replace_content";

  return (
    <li className="rounded-lg border border-zinc-200 p-2.5 dark:border-zinc-800">
      <p className={`flex items-center gap-1.5 text-sm font-medium ${kind.className}`}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {what}
      </p>
      {translation ? (
        <div className="mt-1 grid gap-1.5 text-sm">
          <p className="whitespace-pre-wrap text-zinc-500"><span className="block text-[11px] uppercase tracking-wide">Original</span>{short(text, 400)}</p>
          <p className="whitespace-pre-wrap text-zinc-800 dark:text-zinc-200"><span className="block text-[11px] uppercase tracking-wide text-zinc-500">Translation</span>{short(proposal.after, 400)}</p>
          {proposal.problems.length > 0 && (
            <ul className="list-disc pl-4 text-xs text-amber-700 dark:text-amber-400">
              {proposal.problems.map((problem) => (
                <li key={problem}>Left as it was: {problem}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className={`mt-1 whitespace-pre-wrap text-sm text-zinc-800 dark:text-zinc-200 ${proposal.type === "delete_element" ? "line-through decoration-red-500/70" : ""}`}>
          {short(text, 400)}
        </p>
      )}
      {proposal.reason && <p className="mt-1 truncate text-xs text-zinc-500" title={proposal.reason}>{translation ? proposal.reason : `From: “${proposal.reason}”`}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" onClick={onAccept} disabled={busy} className="flex items-center gap-1 rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50">
          <Check className="h-3.5 w-3.5" aria-hidden="true" />
          Accept
        </button>
        <button type="button" onClick={onReject} disabled={busy} className="flex items-center gap-1 rounded-full border border-zinc-300 px-3 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800">
          <X className="h-3.5 w-3.5" aria-hidden="true" />
          Reject
        </button>
        {target && (
          <button type="button" onClick={() => onShow(target)} className="flex items-center gap-1 px-2 py-1 text-xs text-zinc-500 hover:text-accent">
            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
            Show
          </button>
        )}
      </div>
    </li>
  );
}

/**
 * Changes to the text an AI instruction asked for (brief §19, tracker AI-007):
 * each shown before anything happens -- what would be deleted (as it reads now),
 * added or moved, and where -- and applied only when accepted. A rejected one
 * is simply gone; an accepted one is an ordinary, undoable change.
 */
export function ProposalsList({ source }: { source?: ProposedChange["source"] } = {}) {
  const { document, editor, change } = useDocumentEditor();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const proposals = (document.proposals ?? []).filter((proposal) => !source || proposal.source === source);
  if (proposals.length === 0) return null;

  async function act(proposalId: string, action: typeof acceptProposal) {
    setBusy(proposalId);
    setError(null);
    try {
      await change((documentId) => action(documentId, proposalId));
    } catch (err) {
      setError(errorMessage(err, "Couldn't do that."));
    } finally {
      setBusy(null);
    }
  }

  function show(elementId: string) {
    if (!editor || editor.isDestroyed) return;
    selectElementById(editor, elementId);
    editor.view.dom.querySelector(`[data-element-id="${CSS.escape(elementId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  return (
    <section aria-label="Changes to review" className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Changes to review ({proposals.length})</h3>
      <p className="text-xs text-zinc-500">
        {source === "translation" ? "Translations wait for you here." : "Your instructions asked to change the text."} Nothing changes until you accept.
      </p>
      <ul className="flex flex-col gap-2">
        {proposals.map((proposal) => (
          <Proposal
            key={proposal.id}
            proposal={proposal}
            busy={busy !== null}
            onAccept={() => void act(proposal.id, acceptProposal)}
            onReject={() => void act(proposal.id, rejectProposal)}
            onShow={show}
          />
        ))}
      </ul>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
    </section>
  );
}
