"use client";

import { CheckCheck } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { ProposalCard, useProposalActions } from "@/editor/panels/ProposalsList";
import { RepairSection } from "@/editor/panels/RepairSection";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import { acceptProposalsOfCategory } from "@/services/api";
import type { ChangeCategory, ProposedChange } from "@/types/document";

const CATEGORY_IDS: ChangeCategory[] = ["content", "structure", "format", "translation", "metadata", "preservation"];

/**
 * Review Changes (brief §58 and §89, tracker REV-002): every change the user didn't make
 * themselves -- an instruction's, a translation, a health check's fix -- in one place, grouped
 * by what it touches. Nothing changes until it is accepted. A whole category can be accepted at
 * once, except the content's: changes to the words are accepted one by one, and the server
 * holds back any change that would alter them (REV-003).
 */
export function ReviewPanel() {
  const { document } = useDocumentEditor();
  const t = useI18n().m.edPanels.review;
  const CATEGORIES = CATEGORY_IDS.map((id) => ({ id, ...t.categories[id] }));
  const { busy, error, run, accept, reject, show } = useProposalActions();
  const [filter, setFilter] = useState<ChangeCategory | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const proposals = document.proposals ?? [];

  if (proposals.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <RepairSection onShow={show} />
        <p className="text-sm text-muted">{t.empty}</p>
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
      setOutcome(format(t.accepted, { count: answer.accepted }) + (answer.skipped > 0 ? format(t.skipped, { count: answer.skipped }) : ""));
      return answer.document;
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <RepairSection onShow={show} />
      <div>
        <p className="text-sm font-medium text-foreground">
          {plural(proposals.length, t.toReview)}
        </p>
        <p className="text-xs text-muted">{t.intro}</p>
      </div>

      <div role="group" aria-label={t.filter} className="flex flex-wrap gap-1.5">
        <FilterChip label={format(t.all, { count: proposals.length })} pressed={filter === null} onClick={() => setFilter(null)} />
        {CATEGORIES.filter((category) => byCategory.has(category.id)).map((category) => (
          <FilterChip
            key={category.id}
            label={format(t.chip, { label: category.label, count: byCategory.get(category.id)?.length ?? 0 })}
            pressed={filter === category.id}
            onClick={() => setFilter(filter === category.id ? null : category.id)}
          />
        ))}
      </div>

      {outcome && <p role="status" className="text-xs text-muted">{outcome}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}

      {shown.map((category) => {
        const waiting = byCategory.get(category.id) ?? [];
        return (
          <section key={category.id} aria-label={format(t.sectionLabel, { label: category.label })} className="flex flex-col gap-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
                  {format(t.heading, { label: category.label, count: waiting.length })}
                </h3>
                <p className="text-xs text-muted">{category.about}</p>
              </div>
              {category.id !== "content" && waiting.length > 1 && (
                <button
                  type="button"
                  onClick={() => acceptAll(category.id)}
                  disabled={busy !== null}
                  className="flex shrink-0 items-center gap-1 rounded-full border border-line-strong px-2.5 py-1 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50"
                >
                  <CheckCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  {format(t.acceptAll, { count: waiting.length })}
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
        pressed ? "bg-accent text-accent-foreground ring-accent" : "text-muted ring-line-strong hover:bg-surface-muted"
      }`}
    >
      {label}
    </button>
  );
}
