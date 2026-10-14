"use client";

import { HeartPulse, History, Languages, LayoutTemplate, ListChecks, ListTree, Settings as SettingsIcon, Wand2, X, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { SidePanel, type SidePanelTab } from "@/components/SidePanel";
import { ConflictModal } from "@/editor/ConflictModal";
import { EditableTitle } from "@/editor/EditableTitle";
import { EditorActionBar } from "@/editor/EditorActionBar";
import { EditorCanvas } from "@/editor/EditorCanvas";
import { EditorStateProvider } from "@/editor/EditorState";
import { EditorStatusBar } from "@/editor/EditorStatusBar";
import { EditorToolbar } from "@/editor/EditorToolbar";
import { ExportMenu } from "@/editor/ExportMenu";
import { FidelityPanel } from "@/editor/panels/FidelityPanel";
import { HealthPanel } from "@/editor/panels/HealthPanel";
import { ReviewPanel } from "@/editor/panels/ReviewPanel";
import { HistoryPanel } from "@/editor/panels/HistoryPanel";
import { InstructionsPanel } from "@/editor/panels/InstructionsPanel";
import { PageSettingsPanel } from "@/editor/panels/PageSettingsPanel";
import { PropertiesSidebar } from "@/editor/panels/PropertiesSidebar";
import { StructurePanel } from "@/editor/panels/StructurePanel";
import { TemplatesPanel } from "@/editor/panels/TemplatesPanel";
import { TranslatePanel } from "@/editor/panels/TranslatePanel";
import { StyleAnalysisModal } from "@/editor/StyleAnalysisModal";
import { useEditorEngine } from "@/editor/useEditorEngine";
import { useMediaQuery } from "@/lib/useMediaQuery";
import type { Document } from "@/types/document";

function ChangedElsewhereBanner() {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-4 border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200 sm:px-6"
    >
      <span>
        This document was changed in another tab or window, so your latest change wasn&apos;t saved. Reload to continue from the
        current version.
      </span>
      <button type="button" onClick={() => window.location.reload()} className="shrink-0 rounded-full bg-amber-700 px-3 py-1 text-xs font-medium text-white hover:bg-amber-800">
        Reload
      </button>
    </div>
  );
}

/**
 * The 1.x document editor (корекции.docx §27), still the default: this shell only lays the editor out; what
 * the editor is -- document, text engine, pages, autosave, formatting, undo/redo, actions -- is
 * useEditorEngine, shared with the 2.0 shell (EditorShellV2, ?editor=2). The panels read what they need from
 * EditorState.
 */
export function DocumentEditorShell({ initialDocument }: { initialDocument: Document }) {
  const engine = useEditorEngine(initialDocument);
  const { document, editor, page, autosave, formatting, history } = engine;

  // Below 1100 px the side panels open over the pages; the Templates panel then starts closed.
  const wide = useMediaQuery("(min-width: 1100px)");
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [showStyleAnalysis, setShowStyleAnalysis] = useState(false);

  const sidePanelTabs: SidePanelTab[] = [
    {
      id: "structure",
      label: "Структура",
      icon: <ListTree className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <StructurePanel elements={document.elements} />,
    },
    {
      id: "templates",
      label: "Шаблони",
      icon: <LayoutTemplate className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <TemplatesPanel state={formatting} />,
    },
    {
      id: "instructions",
      label: "Инструкции",
      icon: <Wand2 className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <InstructionsPanel state={formatting} history={history} />,
    },
    {
      id: "translate",
      label: "Превод",
      icon: <Languages className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <TranslatePanel />,
    },
    {
      id: "review",
      label: "Преглед",
      icon: <ListChecks className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <ReviewPanel />,
    },
    {
      id: "settings",
      label: "Настройки",
      icon: <SettingsIcon className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <PageSettingsPanel />,
    },
    {
      id: "history",
      label: "История",
      icon: <History className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <HistoryPanel />,
    },
    {
      id: "health",
      label: "Здраве",
      icon: <HeartPulse className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <HealthPanel />,
    },
    {
      id: "fidelity",
      label: "Проверка",
      icon: <ShieldCheck className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <FidelityPanel />,
    },
  ];

  return (
    <EditorStateProvider value={engine.editorState}>
      <div className="flex h-screen flex-col overflow-hidden">
        <AppHeader
          rightSlot={
            <>
              <EditableTitle title={document.metadata.title} onRename={(title) => void engine.rename(title)} />
              <ExportMenu documentId={document.id} flush={autosave.flush} />
            </>
          }
        />
        {engine.changedElsewhere && <ChangedElsewhereBanner />}
        <div className="relative flex min-h-0 flex-1">
          <SidePanel key={wide ? "wide" : "narrow"} tabs={sidePanelTabs} defaultTabId={wide ? "templates" : null} showHomeLink />

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="border-b border-line px-4 pt-3 pb-0 sm:px-6">
              <EditorToolbar onToggleProperties={() => setPropertiesOpen((open) => !open)} />
            </div>

            <EditorCanvas
              editor={editor}
              settings={document.settings}
              page={page}
              canvasRef={page.canvasRef}
              showHidden={engine.showHidden}
              chrome={engine.chrome}
              lastSectionStart={document.lastSection?.pageNumberStart ?? null}
              onEditChrome={(pageIndex, part, text) => engine.editChrome(pageIndex, part, text)}
            />

            {engine.actionError && (
              <div role="alert" className="flex items-center justify-between gap-3 border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300 sm:px-6">
                <span>{engine.actionError}</span>
                <button type="button" onClick={engine.clearActionError} aria-label="Dismiss" className="shrink-0 hover:text-red-900 dark:hover:text-red-100">
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            )}
            <EditorActionBar
              formatting={formatting}
              onAnalyzeStyle={() => setShowStyleAnalysis(true)}
              onAddElement={(type) => void engine.addElementAfterSelection(type)}
              onSaveNow={autosave.retry}
            />
            <EditorStatusBar
              zoom={page.zoom}
              onZoomChange={page.setZoom}
              onFitWidth={page.fitWidth}
              pageCount={page.pageCount}
              onAddPage={() => void engine.addPageAfterSelection()}
              saveStatus={autosave.status}
              saveProblem={autosave.problem}
              notKept={autosave.notKept}
              proposalCount={(document.proposals ?? []).filter((proposal) => proposal.source !== "health").length}
              fixCount={(document.proposals ?? []).filter((proposal) => proposal.source === "health").length}
              importReport={document.importReport}
              hiddenWords={engine.hiddenWords}
              showHidden={engine.showHidden}
              onToggleHidden={engine.toggleHidden}
              onRetrySave={autosave.retry}
            />
          </div>

          <PropertiesSidebar open={propertiesOpen} onClose={() => setPropertiesOpen(false)} />
        </div>

        {formatting.conflicts && (
          <ConflictModal
            conflicts={formatting.conflicts}
            onCancel={() => formatting.setConflicts(null)}
            onResolve={(resolutions) => formatting.handleApply("conflicts", { resolutions })}
            progress={formatting.applyingFrom === "conflicts" ? formatting.progress : null}
          />
        )}

        {showStyleAnalysis && <StyleAnalysisModal document={document} onClose={() => setShowStyleAnalysis(false)} />}
      </div>
    </EditorStateProvider>
  );
}
