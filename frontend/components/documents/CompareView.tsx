"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import { AppShell } from "@/components/shell/AppShell";
import { Notice } from "@/components/ui/Notice";
import type { ChangeKind } from "@/editor/changeHighlight";
import { formatDateTime } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { errorMessage, getDocument, restoreVersion } from "@/services/api";
import { queryKeys, useComparison, useVersion, useVersions } from "@/services/queries";
import type { Document, DocumentComparison, DocumentVersion, ElementChange } from "@/types/document";

type Words = Messages["compare"];

const CHANGE_COLORS: Record<ElementChange["change"], string> = {
  added: "bg-success",
  removed: "bg-danger",
  edited: "bg-warning",
  retyped: "bg-warning",
  moved: "bg-accent",
};
const SHOWN = 60;

function versionLabel(version: DocumentVersion | undefined, number: number, t: Words): string {
  if (!version) return format(t.version, { number });
  return `${version.current ? t.now : format(t.version, { number: version.number })} · ${version.description}`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-4 shadow-card">
      <h2 className="mb-2 text-sm font-semibold text-foreground">{title}</h2>
      {children}
    </section>
  );
}

function Changes({ comparison }: { comparison: DocumentComparison }) {
  const { m } = useI18n();
  const t = m.compare;
  const properties: Record<string, string> = t.properties;
  const settings: Record<string, string> = t.settings;
  const counts = comparison.structure.reduce<Record<string, number>>((all, change) => ({ ...all, [change.change]: (all[change.change] ?? 0) + 1 }), {});
  const byLabel = comparison.styles.reduce<Record<string, typeof comparison.styles>>((all, change) => ({ ...all, [change.label]: [...(all[change.label] ?? []), change] }), {});
  if (!comparison.structure.length && !comparison.styles.length && !comparison.settings.length) {
    return <p className="text-sm text-muted">{t.noDifferences}</p>;
  }
  const countLine = Object.entries(counts)
    .map(([kind, count]) => format(t.changeCount, { count, label: t.changes[kind as ElementChange["change"]].toLowerCase() }))
    .join(" · ");
  return (
    <div className="flex flex-col gap-4">
      {comparison.structure.length > 0 && (
        <Section title={format(t.content, { counts: countLine })}>
          <ul className="flex flex-col gap-1.5 text-sm">
            {comparison.structure.slice(0, SHOWN).map((change) => (
              <li key={`${change.change}-${change.elementId}`} className="flex items-start gap-2">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${CHANGE_COLORS[change.change]}`} aria-hidden="true" />
                <span className="min-w-0">
                  <span className="font-medium text-foreground">{t.changes[change.change]}</span>{" "}
                  {change.change === "retyped" && (
                    <span className="text-muted">
                      ({change.beforeType} → {change.afterType}){" "}
                    </span>
                  )}
                  <span className="text-muted">“{(change.afterText ?? change.beforeText) || t.empty}”</span>
                </span>
              </li>
            ))}
          </ul>
          {comparison.structure.length > SHOWN && <p className="mt-2 text-xs text-muted">{format(t.more, { count: comparison.structure.length - SHOWN })}</p>}
        </Section>
      )}
      {comparison.styles.length > 0 && (
        <Section title={t.formatting}>
          <dl className="flex flex-col gap-2 text-sm">
            {Object.entries(byLabel).map(([label, changes]) => (
              <div key={label}>
                <dt className="font-medium text-foreground">{label}</dt>
                <dd className="text-muted">
                  {changes.map((change) => (
                    <span key={change.property} className="mr-3 inline-block">
                      {properties[change.property] ?? change.property}: {change.before ?? "—"} → {change.after ?? "—"}
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        </Section>
      )}
      {comparison.settings.length > 0 && (
        <Section title={t.page}>
          <ul className="flex flex-col gap-1 text-sm text-muted">
            {comparison.settings.map((change) => (
              <li key={change.property}>
                {settings[change.property] ?? change.property}: {change.before ?? "—"} → {change.after ?? "—"}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Compare({ current, from, to }: { current: Document; from: number; to?: number }) {
  const { m, locale } = useI18n();
  const t = m.compare;
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
      setRestoreError(errorMessage(err, t.restoreFailed));
      setBusy(false);
    }
  }

  const byNumber = new Map((versions.data ?? []).map((version) => [version.number, version]));
  const select = (value: number | undefined, onChange: (number: number) => void, label: string) => (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-muted">
      {label}
      <select
        value={value ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-10 rounded-xl border border-line bg-surface px-2 text-sm text-foreground focus:border-accent focus:outline-none"
      >
        {(versions.data ?? []).map((version) => (
          <option key={version.number} value={version.number}>
            {versionLabel(version, version.number, t)} ({formatDateTime(version.createdAt, locale)})
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        {select(from, (number) => go(number, toNumber), t.before)}
        {select(toNumber, (number) => go(from, number), t.after)}
        {from !== currentNumber && (
          <button
            type="button"
            onClick={() => setRestoring(true)}
            className="flex h-10 items-center gap-1.5 rounded-xl border border-line-strong px-3 text-sm font-medium text-foreground hover:border-accent hover:text-accent"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" /> {t.restore}
          </button>
        )}
      </div>
      {(versions.error || comparison.error || before.error) && (
        <div className="mt-3">
          <Notice tone="error">{errorMessage(versions.error ?? comparison.error ?? before.error)}</Notice>
        </div>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          <h2 className="mb-2 truncate text-sm font-semibold text-foreground">{versionLabel(byNumber.get(from), from, t)}</h2>
          {before.data ? <DocumentPreview document={before.data} changes={marks.left} /> : <Spinner />}
        </div>
        <div className="min-w-0">
          <h2 className="mb-2 truncate text-sm font-semibold text-foreground">{toNumber !== undefined ? versionLabel(byNumber.get(toNumber), toNumber, t) : t.now}</h2>
          {after ? <DocumentPreview document={after} changes={marks.right} /> : <Spinner />}
        </div>
        <div className="min-w-0 xl:sticky xl:top-6 xl:self-start">{comparison.data ? <Changes comparison={comparison.data} /> : <Spinner />}</div>
      </div>

      {restoring && (
        <ConfirmDialog
          title={format(t.restoreTitle, { number: from })}
          confirmLabel={t.restoreConfirm}
          busy={busy}
          error={restoreError}
          onConfirm={() => void restore()}
          onCancel={() => setRestoring(false)}
        >
          <p>{t.restoreText}</p>
        </ConfirmDialog>
      )}
    </>
  );
}

function Spinner() {
  const { m } = useI18n();
  return (
    <p className="flex items-center gap-2 text-sm text-muted">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {m.common.loading}
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
  const { m } = useI18n();
  const t = m.compare;
  // Its own entry: the editor's (queryKeys.document) lives only while the editor is open.
  const current = useQuery({ queryKey: queryKeys.documentForCompare(documentId), queryFn: () => getDocument(documentId) });

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-[110rem] flex-1 px-4 py-6 sm:px-6">
        <Link href={`/documents/${documentId}`} className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-accent">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {t.back}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{current.data ? format(t.titleNamed, { title: current.data.metadata.title }) : t.title}</h1>
        {current.error ? (
          <div className="mt-4">
            <Notice tone="error">{errorMessage(current.error)}</Notice>
          </div>
        ) : current.data ? (
          <Compare current={current.data} from={from} to={to} />
        ) : (
          <div className="mt-6">
            <Spinner />
          </div>
        )}
      </main>
    </AppShell>
  );
}
