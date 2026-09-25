"use client";

import { useEditor } from "@tiptap/react";
import { LayoutTemplate, ListTree, Settings as SettingsIcon, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { SidePanel, type SidePanelTab } from "@/components/SidePanel";
import type { InsertableType } from "@/editor/AddElementMenu";
import { ConflictModal } from "@/editor/ConflictModal";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { EditableTitle } from "@/editor/EditableTitle";
import { EditorActionBar } from "@/editor/EditorActionBar";
import { EditorCanvas } from "@/editor/EditorCanvas";
import { EditorStateProvider, useDocumentChanges, type EditorState } from "@/editor/EditorState";
import { EditorStatusBar } from "@/editor/EditorStatusBar";
import { EditorToolbar } from "@/editor/EditorToolbar";
import { ExportMenu } from "@/editor/ExportMenu";
import { editorExtensions } from "@/editor/extensions";
import { Pagination } from "@/editor/pagination";
import { InstructionsPanel } from "@/editor/panels/InstructionsPanel";
import { PageSettingsPanel } from "@/editor/panels/PageSettingsPanel";
import { PropertiesSidebar } from "@/editor/panels/PropertiesSidebar";
import { StructurePanel } from "@/editor/panels/StructurePanel";
import { TemplatesPanel } from "@/editor/panels/TemplatesPanel";
import { StyleAnalysisModal } from "@/editor/StyleAnalysisModal";
import { useAutoSave } from "@/editor/useAutoSave";
import { useDocument } from "@/editor/useDocument";
import { useFormatting } from "@/editor/useFormatting";
import { useHistory } from "@/editor/useHistory";
import { usePageSettings, useRepaginate } from "@/editor/usePageSettings";
import { useSelection } from "@/editor/useSelection";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { addElement, addPage, errorMessage, renameDocument } from "@/services/api";
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
      <button type="button" onClick={() => window.location.reload()} className="shrink-0 rounded-full bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700">
        Reload
      </button>
    </div>
  );
}

/**
 * The document editor (корекции.docx §27): this shell only lays the editor out
 * and wires its parts together. The document is server state (useDocument);
 * typing is saved by useAutoSave; every other change goes through `change`
 * (EditorState.tsx), which saves pending typing first; formatting, undo/redo,
 * selection, page geometry and export each have their own hook; the panels
 * read what they need from EditorState.
 */
export function DocumentEditorShell({ initialDocument }: { initialDocument: Document }) {
  const { document, documentRef, setDocument, changedElsewhere } = useDocument(initialDocument);
  const page = usePageSettings(document.settings);
  const { setPageCount, canvasRef } = page;

  // Pagination reads the page geometry from the page container's data-*
  // attributes (EditorCanvas), so the editor is never recreated when it changes.
  const extensions = useMemo(() => [...editorExtensions, Pagination.configure({ onPageCount: setPageCount })], [setPageCount]);
  const editor = useEditor({ extensions, content: documentToTiptapJSON(initialDocument), immediatelyRender: false });

  const selection = useSelection(editor, document);
  const autosave = useAutoSave(editor, documentRef, setDocument);
  const { apply, change } = useDocumentChanges(editor, documentRef, setDocument, autosave.flush);
  const formatting = useFormatting(document, apply, autosave.flush);
  const history = useHistory(change);
  useRepaginate(editor, document.settings, page);

  // A formatting job replaces the document when it finishes, so typing meanwhile
  // would be lost: the pages are read-only until it is done.
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.setEditable(!formatting.isApplying, false);
  }, [editor, formatting.isApplying]);

  // Below 1100 px the side panels open over the pages; the Templates panel then starts closed.
  const wide = useMediaQuery("(min-width: 1100px)");
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [showStyleAnalysis, setShowStyleAnalysis] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(action: (documentId: string) => Promise<Document>) {
    setActionError(null);
    try {
      await change(action);
    } catch (err) {
      setActionError(errorMessage(err, "That change couldn't be made."));
    }
  }
  const afterSelected = () => selection.selectedElementId ?? undefined;
  const handleAddPage = () => run((documentId) => addPage(documentId, afterSelected()));
  const handleAddElement = (elementType: InsertableType) => run((documentId) => addElement(documentId, { elementType, afterElementId: afterSelected() }));
  const handleRename = (title: string) => run((documentId) => renameDocument(documentId, title));

  const editorState: EditorState = { document, editor, selection, change, flush: autosave.flush };

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
      id: "settings",
      label: "Настройки",
      icon: <SettingsIcon className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <PageSettingsPanel />,
    },
  ];

  return (
    <EditorStateProvider value={editorState}>
      <div className="flex h-screen flex-col overflow-hidden">
        <AppHeader
          rightSlot={
            <>
              <EditableTitle title={document.metadata.title} onRename={(title) => void handleRename(title)} />
              <ExportMenu documentId={document.id} flush={autosave.flush} />
            </>
          }
        />
        {changedElsewhere && <ChangedElsewhereBanner />}
        <div className="relative flex min-h-0 flex-1">
          <SidePanel key={wide ? "wide" : "narrow"} tabs={sidePanelTabs} defaultTabId={wide ? "templates" : null} showHomeLink />

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="border-b border-zinc-200 px-4 pt-3 pb-0 dark:border-zinc-800 sm:px-6">
              <EditorToolbar onToggleProperties={() => setPropertiesOpen((open) => !open)} />
            </div>

            <EditorCanvas editor={editor} settings={document.settings} page={page} canvasRef={canvasRef} />

            {actionError && (
              <div role="alert" className="flex items-center justify-between gap-3 border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300 sm:px-6">
                <span>{actionError}</span>
                <button type="button" onClick={() => setActionError(null)} aria-label="Dismiss" className="shrink-0 hover:text-red-900 dark:hover:text-red-100">
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            )}
            <EditorActionBar
              formatting={formatting}
              onAnalyzeStyle={() => setShowStyleAnalysis(true)}
              onAddElement={(type) => void handleAddElement(type)}
              onSaveNow={autosave.retry}
            />
            <EditorStatusBar
              zoom={page.zoom}
              onZoomChange={page.setZoom}
              onFitWidth={page.fitWidth}
              pageCount={page.pageCount}
              onAddPage={() => void handleAddPage()}
              saveStatus={autosave.status}
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
