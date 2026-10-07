"use client";

import { CheckCheck } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { ProposalCard, useProposalActions } from "@/editor/panels/ProposalsList";
import { RepairSection } from "@/editor/panels/RepairSection";
import { acceptProposalsOfCategory } from "@/services/api";
import type { ChangeCategory, ProposedChange } from "@/types/document";

const CATEGORIES: { id: ChangeCategory; label: string; about: string }[] = [
  { id: "content", label: "Content", about: "Changes to the words. Accept each one yourself." },
  { id: "structure", label: "Structure", about: "Headings, lists, page breaks, empty paragraphs." },
  { id: "format", label: "Format", about: "How things look: fonts, sizes, colours, widths, margins." },
  { id: "translation", label: "Translation", about: "Blocks translated for you." },
  { id: "metadata", label: "Metadata", about: "Language marks and other information about the text." },
  { id: "preservation", label: "Preservation", about: "What is kept from the original file." },
];

/**
 * Review Changes (brief §58 and §89, tracker REV-002): every change the user didn't make
 * themselves -- an instruction's, a translation, a health check's fix -- in one place, grouped
 * by what it touches. Nothing changes until it is accepted. A whole category can be accepted at
 * once, except the content's: changes to the words are accepted one by one, and the server
 * holds back any change that would alter them (REV-003).
 */
export function ReviewPanel() {
  const { document } = useDocumentEditor();
  const { busy, error, run, accept, reject, show } = useProposalActions();
  const [filter, setFilter] = useState<ChangeCategory | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const proposals = document.proposals ?? [];

  if (proposals.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <RepairSection onShow={show} />
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Nothing waits for review. Changes an instruction, a translation, a health check or a repair proposes show up here, and nothing changes until you
          accept them.
        </p>
      </div>
    );
  }

  const byCategory = new Map<ChangeCategory, ProposedChange[]>();
  for (const proposal of proposals) byCategory.set(proposal.category, [...(byCategory.get(proposal.category) ?? []), proposal]);
  const shown = CATEGORIES.filter((category) => byCategory.has(category.id) && (filter === null || filter === category.id));

  function acceptAll(category: ChangeCategory) {
    setOutcome(null);
    void run(`all:${category}`, async (documentId) => {
      const answer = await acceptProposalsOfCategory(documentId, category);
      setOutcome(
        `Accepted ${answer.accepted}.` +
          (answer.skipped > 0 ? ` ${answer.skipped} left waiting: they change the words or no longer fit, so accept or reject each one.` : ""),
      );
      return answer.document;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <RepairSection onShow={show} />
      <div>
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          {proposals.length} change{proposals.length === 1 ? "" : "s"} to review
        </p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">Nothing changes until you accept. Accepted changes can be undone.</p>
      </div>

      <div role="group" aria-label="Show changes" className="flex flex-wrap gap-1.5">
        <FilterChip label={`All ${proposals.length}`} pressed={filter === null} onClick={() => setFilter(null)} />
        {CATEGORIES.filter((category) => byCategory.has(category.id)).map((category) => (
          <FilterChip
            key={category.id}
            label={`${category.label} ${byCategory.get(category.id)?.length ?? 0}`}
            pressed={filter === category.id}
            onClick={() => setFilter(filter === category.id ? null : category.id)}
          />
        ))}
      </div>

      {outcome && <p role="status" className="text-xs text-zinc-600 dark:text-zinc-400">{outcome}</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {shown.map((category) => {
        const waiting = byCategory.get(category.id) ?? [];
        return (
          <section key={category.id} aria-label={`${category.label} changes`} className="flex flex-col gap-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                  {category.label} ({waiting.length})
                </h3>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">{category.about}</p>
              </div>
              {category.id !== "content" && waiting.length > 1 && (
                <button
                  type="button"
                  onClick={() => acceptAll(category.id)}
                  disabled={busy !== null}
                  className="flex shrink-0 items-center gap-1 rounded-full border border-zinc-300 px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  <CheckCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  Accept all {waiting.length}
                </button>
              )}
            </div>
            <ul className="flex flex-col gap-2">
              {waiting.map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  busy={busy !== null}
                  onAccept={() => void accept(proposal.id)}
                  onReject={() => void reject(proposal.id)}
                  onShow={show}
                  showSource
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function FilterChip({ label, pressed, onClick }: { label: string; pressed: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${
        pressed ? "bg-accent text-accent-foreground ring-accent" : "text-zinc-600 ring-zinc-300 hover:bg-zinc-100 dark:text-zinc-400 dark:ring-zinc-700 dark:hover:bg-zinc-800"
      }`}
    >
      {label}
    </button>
  );
}
