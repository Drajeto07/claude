"use client";

import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { LayoutTemplate, ListTree, Send, Settings as SettingsIcon, Wand2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";

import { AppHeader } from "@/components/AppHeader";
import { AddElementMenu } from "@/components/AddElementMenu";
import { ConflictModal } from "@/components/ConflictModal";
import { StyleAnalysisModal } from "@/components/StyleAnalysisModal";
import { EditorContextBar } from "@/components/EditorContextBar";
import { ExportPanel } from "@/components/ExportPanel";
import { InstructionsPanel } from "@/components/InstructionsPanel";
import { PageSettingsPanel } from "@/components/PageSettingsPanel";
import { RightSidebar } from "@/components/RightSidebar";
import { SidePanel, type SidePanelTab } from "@/components/SidePanel";
import { StructurePanel } from "@/components/StructurePanel";
import { TemplatesPanel } from "@/components/TemplatesPanel";
import { ViewControls, type SaveStatus } from "@/components/ViewControls";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { getSelectedElementId } from "@/editor/elementId";
import { editorExtensions } from "@/editor/extensions";
import { reconcileElements } from "@/editor/tiptapToDocument";
import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";
import { useFormattingState } from "@/editor/useFormattingState";
import { addElement, addPage, rememberRevision, renameDocument, REVISION_CONFLICT_EVENT, updateContent } from "@/services/api";
import type { Document } from "@/types/document";

// After setContent() replaces the whole document, ProseMirror's selection
// resets -- without this, editing one property in PropertiesPanel would
// deselect the element being edited, forcing a re-click after every change.
function selectElementById(editor: Editor, elementId: string) {
  let targetPos: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (targetPos !== null) return false;
    if (node.attrs?.elementId === elementId) {
      targetPos = pos;
      return false;
    }
    return true;
  });
  if (targetPos !== null) editor.commands.setTextSelection(targetPos + 1);
}

const PAGE_DIMENSIONS_MM: Record<string, { width: number; height: number }> = {
  A4: { width: 210, height: 297 },
  Letter: { width: 216, height: 279 },
  Legal: { width: 216, height: 356 },
};

const PX_PER_MM = 96 / 25.4;
const SEAM_BAND_PX = 14;
const AUTOSAVE_DEBOUNCE_MS = 1200;

// Continuous-scroll single-page visual approximation only -- real multi-page
// reflow, where content actually moves between fixed-height pages as you
// type, is a separate, much bigger engineering effort (no Tiptap/ProseMirror
// library does this for free). Page BREAKS are real (ElementType.PAGE_BREAK,
// see editor/pageBreak.ts) -- only the reflow-as-you-type part is not.
function pageWidthMm(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  return orientation === "landscape" ? dimensions.height : dimensions.width;
}

function pageHeightPx(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  const heightMm = orientation === "landscape" ? dimensions.width : dimensions.height;
  return heightMm * PX_PER_MM;
}

// A shadow band sits at the START of each repeat unit, and the repeat unit's
// length is exactly `heightPx` (the position of the last color-stop) -- that
// combination is what makes seams land on exact multiples of the page height
// with no cumulative drift. backgroundPosition then shifts the whole pattern
// down by one unit, so the first seam appears *after* page 1 instead of
// right at the top edge.
function pageSeamStyle(heightPx: number): CSSProperties {
  return {
    backgroundImage: `repeating-linear-gradient(to bottom, rgba(128,128,128,0.35) 0px, rgba(128,128,128,0.12) 6px, transparent ${SEAM_BAND_PX}px, transparent ${heightPx}px)`,
    backgroundPosition: `0 ${heightPx}px`,
  };
}

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const CANVAS_SIDE_PADDING_PX = 48; // matches the scroll container's px-4/sm:px-6

function EditableTitle({ title, onRename }: { title: string; onRename: (title: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  function commit() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== title) onRename(trimmed);
    else setDraft(title);
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setDraft(title);
            setEditing(false);
          }
        }}
        className="max-w-[240px] rounded border border-accent bg-white px-1.5 py-0.5 text-sm font-medium text-zinc-900 focus:outline-none dark:bg-zinc-900 dark:text-zinc-50"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setDraft(title);
        setEditing(true);
      }}
      title="Rename document"
      className="group flex max-w-[240px] items-center gap-1.5 truncate text-sm font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
    >
      <span className="truncate">{title}</span>
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5 shrink-0 opacity-0 group-hover:opacity-100">
        <path d="M13.586 3.586a2 2 0 1 1 2.828 2.828l-.793.793-2.828-2.828.793-.793ZM11.379 5.793 3 14.172V17h2.828l8.38-8.379-2.83-2.828Z" />
      </svg>
    </button>
  );
}

export function DocumentEditor({ initialDocument }: { initialDocument: Document }) {
  const [doc, setDoc] = useState(initialDocument);
  const [pageCount, setPageCount] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [aiQuickInput, setAiQuickInput] = useState("");
  const [showStyleAnalysis, setShowStyleAnalysis] = useState(false);
  const paperRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const docRef = useRef(doc);
  useEffect(() => {
    docRef.current = doc;
  }, [doc]);
  const [changedElsewhere, setChangedElsewhere] = useState(false);
  // The page was rendered on the server, so this tab's write queue (services/api.ts)
  // learns the starting revision here; every later response keeps it current.
  useEffect(() => {
    rememberRevision(initialDocument);
  }, [initialDocument]);
  useEffect(() => {
    function onConflict(event: Event) {
      if ((event as CustomEvent<{ documentId: string }>).detail.documentId === initialDocument.id) {
        setChangedElsewhere(true);
      }
    }
    window.addEventListener(REVISION_CONFLICT_EVENT, onConflict);
    return () => window.removeEventListener(REVISION_CONFLICT_EVENT, onConflict);
  }, [initialDocument.id]);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flushPromiseRef = useRef<Promise<Document> | null>(null);

  const editor = useEditor({
    extensions: editorExtensions,
    content: documentToTiptapJSON(doc),
    immediatelyRender: false,
  });
  useEditorForceUpdate(editor);
  const selectedElementId = editor ? getSelectedElementId(editor) : null;

  const { settings } = doc;
  const heightPx = pageHeightPx(settings.pageSize, settings.orientation);

  // Stage 0: reconciles live Tiptap edits back into the stored document --
  // without this, typing directly in the editor was never sent to the
  // backend at all, and every *other* mutation (format/undo/style change)
  // silently discarded it the moment it replaced the editor's content.
  //
  // Every mutating action calls this first (see onBeforeMutate below), and
  // a blur also calls it directly -- both can fire from the *same* click
  // (a button that both blurs the editor and triggers its own mutation).
  // Confirmed live: without promise-sharing, the second caller saw "already
  // in flight" and returned immediately instead of waiting, so the mutation
  // it then fired could still race the first flush's request. Concurrent
  // callers now share and await the *same* in-flight promise instead.
  const flushContent = useCallback((): Promise<Document> => {
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    if (flushPromiseRef.current) return flushPromiseRef.current;

    const currentEditor = editor;
    if (!currentEditor) return Promise.resolve(docRef.current);

    const tiptapContent = (currentEditor.getJSON().content ?? []) as Parameters<typeof reconcileElements>[0];
    const reconciled = reconcileElements(tiptapContent, docRef.current.elements);
    if (JSON.stringify(reconciled) === JSON.stringify(docRef.current.elements)) {
      return Promise.resolve(docRef.current); // nothing actually changed -- skip the round trip
    }

    setSaveStatus("saving");
    const promise = (async () => {
      try {
        const updated = await updateContent(docRef.current.id, reconciled);
        docRef.current = updated;
        setDoc(updated);
        setSaveStatus("saved");
        return updated;
      } catch {
        setSaveStatus("error");
        return docRef.current;
      } finally {
        flushPromiseRef.current = null;
      }
    })();
    flushPromiseRef.current = promise;
    return promise;
  }, [editor]);

  useEffect(() => {
    if (!editor) return;
    function scheduleAutosave() {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = setTimeout(() => void flushContent(), AUTOSAVE_DEBOUNCE_MS);
    }
    function flushNow() {
      void flushContent();
    }
    editor.on("update", scheduleAutosave);
    editor.on("blur", flushNow);
    return () => {
      editor.off("update", scheduleAutosave);
      editor.off("blur", flushNow);
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [editor, flushContent]);

  // Estimates page count from rendered content height vs. the configured
  // page height -- still an *estimate* within a page's own flow (real
  // reflow is out of scope, see above), but the page *count* itself is
  // exact once real page breaks exist (counted server-side in doc.elements,
  // not from pixels) -- see pageBreakCount below.
  useEffect(() => {
    const node = paperRef.current;
    if (!node) return;
    const observer = new ResizeObserver(() => {
      setPageCount(Math.max(1, Math.ceil(node.scrollHeight / zoom / heightPx)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [heightPx, zoom]);

  const pageBreakCount = doc.elements.filter((el) => el.type === "page_break").length;

  function applyDocumentUpdate(updated: Document) {
    const previousSelection = editor ? getSelectedElementId(editor) : null;
    docRef.current = updated;
    setDoc(updated);
    editor?.commands.setContent(documentToTiptapJSON(updated));
    if (editor && previousSelection) selectElementById(editor, previousSelection);
  }

  const formatting = useFormattingState(doc, applyDocumentUpdate, flushContent);

  async function handleAddPage() {
    await flushContent(); // never insert a page break ahead of not-yet-saved typing
    const updated = await addPage(docRef.current.id, selectedElementId ?? undefined);
    applyDocumentUpdate(updated);
  }

  async function handleAddElement(elementType: "paragraph" | "heading" | "list" | "table") {
    await flushContent(); // never insert ahead of not-yet-saved typing
    const updated = await addElement(docRef.current.id, { elementType, afterElementId: selectedElementId ?? undefined });
    applyDocumentUpdate(updated);
  }

  async function handleRename(title: string) {
    await flushContent();
    applyDocumentUpdate(await renameDocument(docRef.current.id, title));
  }

  function handleFitWidth() {
    const container = canvasRef.current;
    if (!container) return;
    const pageWidthPx = pageWidthMm(settings.pageSize, settings.orientation) * PX_PER_MM;
    const available = container.clientWidth - CANVAS_SIDE_PADDING_PX;
    setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, available / pageWidthPx)));
  }

  function handleAiQuickSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aiQuickInput.trim()) return;
    formatting.setInstructionsText(aiQuickInput);
    setAiQuickInput("");
    void formatting.handleApply();
  }

  const pageWidth = `${pageWidthMm(settings.pageSize, settings.orientation)}mm`;
  const paperPadding: CSSProperties = {
    paddingTop: `${settings.marginTopCm}cm`,
    paddingBottom: `${settings.marginBottomCm}cm`,
    paddingLeft: `${settings.marginLeftCm}cm`,
    paddingRight: `${settings.marginRightCm}cm`,
  };

  const sidePanelTabs: SidePanelTab[] = [
    {
      id: "structure",
      label: "Структура",
      icon: <ListTree className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <StructurePanel elements={doc.elements} />,
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
      content: <InstructionsPanel document={doc} state={formatting} />,
    },
    {
      id: "settings",
      label: "Настройки",
      icon: <SettingsIcon className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <PageSettingsPanel document={doc} onUpdated={applyDocumentUpdate} onBeforeMutate={flushContent} />,
    },
  ];

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <AppHeader
        rightSlot={
          <>
            <EditableTitle title={doc.metadata.title} onRename={handleRename} />
            <ExportPanel documentId={doc.id} />
          </>
        }
      />
      {changedElsewhere && (
        <div
          role="alert"
          className="flex items-center justify-between gap-4 border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200 sm:px-6"
        >
          <span>
            This document was changed in another tab or window, so your latest change wasn&apos;t saved. Reload to
            continue from the current version.
          </span>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="shrink-0 rounded-full bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700"
          >
            Reload
          </button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <SidePanel tabs={sidePanelTabs} defaultTabId="templates" showHomeLink />

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="border-b border-zinc-200 px-4 pt-3 pb-0 dark:border-zinc-800 sm:px-6">
            <EditorContextBar editor={editor} />
          </div>

          <div ref={canvasRef} className="flex-1 overflow-y-auto px-4 py-8 sm:px-6">
            <p className="mx-auto mb-6 max-w-3xl text-center text-xs text-zinc-400">
              Edits save automatically a moment after you stop typing. Page breaks are real and export the same way
              they look here; content still flows continuously *within* a page rather than auto-reflowing across one.
            </p>

            <div className="mx-auto" style={{ width: pageWidth, zoom }}>
              {settings.header && (
                <p className="mb-2 border-b border-zinc-200 pb-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
                  {settings.header}
                </p>
              )}
              <div
                ref={paperRef}
                className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
                style={{ ...paperPadding, ...pageSeamStyle(heightPx) }}
              >
                <EditorContent editor={editor} />
              </div>
              {settings.footer && (
                <p className="mt-2 border-t border-zinc-200 pt-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
                  {settings.footer}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 border-t border-zinc-200 bg-white px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950 sm:px-6">
            <form onSubmit={handleAiQuickSubmit} className="flex flex-1 items-center gap-2">
              <Wand2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
              <input
                value={aiQuickInput}
                onChange={(e) => setAiQuickInput(e.target.value)}
                placeholder='e.g. "Add a page after the intro"'
                aria-label="AI assistant instruction"
                className="w-full max-w-md rounded-full border border-zinc-300 bg-zinc-50 px-3 py-1.5 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
              <button
                type="submit"
                disabled={formatting.isApplying || !aiQuickInput.trim()}
                aria-label="Send"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Send className="h-4 w-4" aria-hidden="true" />
              </button>
            </form>
            <span className="hidden text-xs text-zinc-400 sm:inline">AI помощник</span>
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowStyleAnalysis(true)}
                className="rounded-full border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400 dark:hover:border-zinc-700"
              >
                Провери стила
              </button>
              <button
                type="button"
                onClick={() => setShowStyleAnalysis(true)}
                className="rounded-full border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400 dark:hover:border-zinc-700"
              >
                Анализирай текста
              </button>
              <AddElementMenu onAdd={(type) => void handleAddElement(type)} />
              <button
                type="button"
                onClick={() => void flushContent()}
                className="rounded-full bg-accent px-4 py-1.5 text-xs font-medium text-accent-foreground transition-opacity hover:opacity-90"
              >
                Приложи промени
              </button>
            </div>
          </div>

          <ViewControls
            zoom={zoom}
            onZoomChange={setZoom}
            onFitWidth={handleFitWidth}
            pageCount={pageCount}
            pageBreakCount={pageBreakCount}
            onAddPage={() => void handleAddPage()}
            saveStatus={saveStatus}
          />
        </div>

        <RightSidebar document={doc} selectedElementId={selectedElementId} onUpdated={applyDocumentUpdate} onBeforeMutate={flushContent} />
      </div>

      {formatting.conflicts && (
        <ConflictModal
          conflicts={formatting.conflicts}
          onCancel={() => formatting.setConflicts(null)}
          onResolve={(resolutions) => formatting.handleApply(resolutions)}
        />
      )}

      {showStyleAnalysis && <StyleAnalysisModal document={doc} onClose={() => setShowStyleAnalysis(false)} />}
    </div>
  );
}
