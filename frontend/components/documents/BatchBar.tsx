"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Wand2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { batchFormat, errorMessage, getBatch } from "@/services/api";
import { queryKeys, useTemplates } from "@/services/queries";
import type { Batch } from "@/types/document";

/**
 * What can be done to the documents ticked in the list at once (FEAT-001, brief §61): one
 * template applied to all of them, as a batch of format jobs followed here until each is done.
 * A document the template's rules conflict with is named, to open and resolve on its own.
 */
export function BatchBar({ selected, onClear }: { selected: string[]; onClear: () => void }) {
  const queryClient = useQueryClient();
  const { data: templates } = useTemplates();
  const [templateId, setTemplateId] = useState("");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
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
      setBatchId((await batchFormat(selected, templateId)).id);
    } catch (err) {
      setError(errorMessage(err, "Couldn't start formatting the documents."));
    } finally {
      setStarting(false);
    }
  }

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
        disabled={!templateId || starting || (batchId !== null && !finished)}
        className="flex items-center gap-1.5 rounded-full bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
      >
        <Wand2 className="h-3.5 w-3.5" aria-hidden="true" />
        Apply to {selected.length} document{selected.length === 1 ? "" : "s"}
      </button>
      <button type="button" onClick={onClear} className="ml-auto flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        <X className="h-3.5 w-3.5" aria-hidden="true" /> Clear selection
      </button>
      {batch && (
        <p role="status" className="basis-full text-xs text-zinc-700 dark:text-zinc-300">
          {!finished && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {batch.done} of {batch.total} done
          {batch.conflicts > 0 && `; ${batch.conflicts} with conflicts to resolve (open each to choose)`}
          {batch.failed > 0 && `; ${batch.failed} failed`}.
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
