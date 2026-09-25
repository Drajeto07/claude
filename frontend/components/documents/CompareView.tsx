"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import type { ChangeKind } from "@/editor/changeHighlight";
import { formatDateTime } from "@/lib/format";
import { errorMessage, getDocument, restoreVersion } from "@/services/api";
import { queryKeys, useComparison, useVersion, useVersions } from "@/services/queries";
import type { Document, DocumentComparison, DocumentVersion, ElementChange } from "@/types/document";

const PROPERTY_LABELS: Record<string, string> = {
  "font-family": "Font",
  "font-size": "Size",
  "font-weight": "Weight",
  "font-style": "Style",
  "text-decoration": "Underline",
  color: "Colour",
  "text-align": "Alignment",
  "line-height": "Line height",
  "--line-spacing": "Line spacing",
  "margin-top": "Space before",
  "margin-bottom": "Space after",
  "text-indent": "First-line indent",
  "margin-left": "Indent",
  "padding-left": "Indent",
  width: "Width",
  alignment: "Alignment",
};
const SETTING_LABELS: Record<string, string> = {
  pageSize: "Page size",
  orientation: "Orientation",
  marginTopCm: "Top margin (cm)",
  marginBottomCm: "Bottom margin (cm)",
  marginLeftCm: "Left margin (cm)",
  marginRightCm: "Right margin (cm)",
  header: "Header",
  footer: "Footer",
  showPageNumbers: "Page numbers",
};
const CHANGE_LABELS: Record<ElementChange["change"], string> = {
  added: "Added",
  removed: "Removed",
  edited: "Edited",
  retyped: "Changed kind",
  moved: "Moved",
};
const CHANGE_COLORS: Record<ElementChange["change"], string> = {
  added: "bg-green-600",
  removed: "bg-red-600",
  edited: "bg-yellow-600",
  retyped: "bg-yellow-600",
  moved: "bg-blue-600",
};
const SHOWN = 60;

function versionLabel(version: DocumentVersion | undefined, number: number): string {
  if (!version) return `Version ${number}`;
  return `${version.current ? "Now" : `Version ${version.number}`} · ${version.description}`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-2 text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
      {children}
    </section>
  );
}

function Changes({ comparison }: { comparison: DocumentComparison }) {
  const counts = comparison.structure.reduce<Record<string, number>>((all, change) => ({ ...all, [change.change]: (all[change.change] ?? 0) + 1 }), {});
  const byLabel = comparison.styles.reduce<Record<string, typeof comparison.styles>>((all, change) => ({ ...all, [change.label]: [...(all[change.label] ?? []), change] }), {});
  if (!comparison.structure.length && !comparison.styles.length && !comparison.settings.length) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">No differences between these versions.</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {comparison.structure.length > 0 && (
        <Section title={`Content: ${Object.entries(counts).map(([kind, count]) => `${count} ${CHANGE_LABELS[kind as ElementChange["change"]].toLowerCase()}`).join(" · ")}`}>
          <ul className="flex flex-col gap-1.5 text-sm">
            {comparison.structure.slice(0, SHOWN).map((change) => (
              <li key={`${change.change}-${change.elementId}`} className="flex items-start gap-2">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${CHANGE_COLORS[change.change]}`} aria-hidden="true" />
                <span className="min-w-0">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">{CHANGE_LABELS[change.change]}</span>{" "}
                  {change.change === "retyped" && (
                    <span className="text-zinc-500">
                      ({change.beforeType} → {change.afterType}){" "}
                    </span>
                  )}
                  <span className="text-zinc-600 dark:text-zinc-400">“{(change.afterText ?? change.beforeText) || "(empty)"}”</span>
                </span>
              </li>
            ))}
          </ul>
          {comparison.structure.length > SHOWN && <p className="mt-2 text-xs text-zinc-500">…and {comparison.structure.length - SHOWN} more.</p>}
        </Section>
      )}
      {comparison.styles.length > 0 && (
        <Section title="Formatting">
          <dl className="flex flex-col gap-2 text-sm">
            {Object.entries(byLabel).map(([label, changes]) => (
              <div key={label}>
                <dt className="font-medium text-zinc-800 dark:text-zinc-200">{label}</dt>
                <dd className="text-zinc-600 dark:text-zinc-400">
                  {changes.map((change) => (
                    <span key={change.property} className="mr-3 inline-block">
                      {PROPERTY_LABELS[change.property] ?? change.property}: {change.before ?? "—"} → {change.after ?? "—"}
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </Section>
      )}
      {comparison.settings.length > 0 && (
        <Section title="Page">
          <ul className="flex flex-col gap-1 text-sm text-zinc-600 dark:text-zinc-400">
            {comparison.settings.map((change) => (
              <li key={change.property}>
                {SETTING_LABELS[change.property] ?? change.property}: {change.before ?? "—"} → {change.after ?? "—"}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Compare({ current, from, to }: { current: Document; from: number; to?: number }) {
  const router = useRouter();
  const versions = useVersions(current.id, current.revision);
  const currentNumber = versions.data?.find((version) => version.current)?.number;
  const toNumber = to ?? currentNumber;
  const comparison = useComparison(current.id, from, to, current.revision);
  const before = useVersion(current.id, from);
  const olderAfter = useVersion(current.id, to !== undefined && to !== currentNumber ? to : undefined);
  const after = to === undefined || to === currentNumber ? current : olderAfter.data;
  const [restoring, setRestoring] = useState(false);
  const [busy, setBusy] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const marks = useMemo(() => {
    const left: Record<string, ChangeKind> = {};
    const right: Record<string, ChangeKind> = {};
    for (const change of comparison.data?.structure ?? []) {
      if (change.change !== "added") left[change.elementId] = change.change;
      if (change.change !== "removed") right[change.elementId] = change.change;
    }
    return { left, right };
  }, [comparison.data]);

  function go(nextFrom: number, nextTo: number | undefined) {
    const query = new URLSearchParams({ from: String(nextFrom) });
    if (nextTo !== undefined && nextTo !== currentNumber) query.set("to", String(nextTo));
    router.replace(`/documents/${current.id}/compare?${query}`);
  }

  async function restore() {
    setBusy(true);
    setRestoreError(null);
    try {
      await restoreVersion(current.id, from);
      router.push(`/documents/${current.id}`);
    } catch (err) {
      setRestoreError(errorMessage(err, "That version couldn't be restored."));
      setBusy(false);
    }
  }

  const byNumber = new Map((versions.data ?? []).map((version) => [version.number, version]));
  const select = (value: number | undefined, onChange: (number: number) => void, label: string) => (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
      {label}
      <select
        value={value ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
        className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
      >
        {(versions.data ?? []).map((version) => (
          <option key={version.number} value={version.number}>
            {versionLabel(version, version.number)} ({formatDateTime(version.createdAt)})
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        {select(from, (number) => go(number, toNumber), "Before")}
        {select(toNumber, (number) => go(from, number), "After")}
        {from !== currentNumber && (
          <button
            type="button"
            onClick={() => setRestoring(true)}
            className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-2 text-sm font-medium text-zinc-700 hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-300"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" /> Restore the “before” version
          </button>
        )}
      </div>
      {(versions.error || comparison.error || before.error) && (
        <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
          {errorMessage(versions.error ?? comparison.error ?? before.error)}
        </p>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          <h2 className="mb-2 truncate text-sm font-semibold text-zinc-900 dark:text-zinc-50">{versionLabel(byNumber.get(from), from)}</h2>
          {before.data ? <DocumentPreview document={before.data} changes={marks.left} /> : <Spinner />}
        </div>
        <div className="min-w-0">
          <h2 className="mb-2 truncate text-sm font-semibold text-zinc-900 dark:text-zinc-50">{toNumber !== undefined ? versionLabel(byNumber.get(toNumber), toNumber) : "Now"}</h2>
          {after ? <DocumentPreview document={after} changes={marks.right} /> : <Spinner />}
        </div>
        <div className="min-w-0 xl:sticky xl:top-6 xl:self-start">{comparison.data ? <Changes comparison={comparison.data} /> : <Spinner />}</div>
      </div>

      {restoring && (
        <ConfirmDialog
          title={`Restore version ${from}?`}
          confirmLabel="Restore"
          busy={busy}
          error={restoreError}
          onConfirm={() => void restore()}
          onCancel={() => setRestoring(false)}
        >
          <p>The document goes back to how it was in this version. This is saved as a new change, so you can undo it afterwards.</p>
        </ConfirmDialog>
      )}
    </>
  );
}

function Spinner() {
  return (
    <p className="flex items-center gap-2 text-sm text-zinc-500">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
    </p>
  );
}

/**
 * Before and after (корекции.docx §39) and looking at an old version (§31): two
 * versions of a document side by side -- by default the original and the
 * document now -- with the blocks that changed marked, and what changed in
 * content, formatting and page setup listed beside them.
 */
export function CompareView({ documentId, from, to }: { documentId: string; from: number; to?: number }) {
  // Its own entry: the editor's (queryKeys.document) lives only while the editor is open.
  const current = useQuery({ queryKey: queryKeys.documentForCompare(documentId), queryFn: () => getDocument(documentId) });

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-[110rem] flex-1 px-4 py-6 sm:px-6">
        <Link href={`/documents/${documentId}`} className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-accent dark:text-zinc-400">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back to the document
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Before and after{current.data ? `: ${current.data.metadata.title}` : ""}
        </h1>
        {current.error ? (
          <p role="alert" className="mt-4 text-sm text-red-600 dark:text-red-400">
            {errorMessage(current.error)}
          </p>
        ) : current.data ? (
          <Compare current={current.data} from={from} to={to} />
        ) : (
          <div className="mt-6">
            <Spinner />
          </div>
        )}
      </main>
    </div>
  );
}
