"use client";

import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { LayoutTemplate, ListTree, Send, Settings as SettingsIcon, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react";

import { AppHeader } from "@/components/AppHeader";
import { AddElementMenu } from "@/components/AddElementMenu";
import { ConflictModal } from "@/components/ConflictModal";
import { StyleAnalysisModal } from "@/components/StyleAnalysisModal";
import { EditorContextBar } from "@/components/EditorContextBar";
import { ExportPanel } from "@/components/ExportPanel";
import { InstructionsPanel } from "@/components/InstructionsPanel";
import { JobProgressBar } from "@/components/JobProgressBar";
import { PageSettingsPanel } from "@/components/PageSettingsPanel";
import { RightSidebar } from "@/components/RightSidebar";
import { SidePanel, type SidePanelTab } from "@/components/SidePanel";
import { StructurePanel } from "@/components/StructurePanel";
import { TemplatesPanel } from "@/components/TemplatesPanel";
import { ViewControls, type SaveStatus } from "@/components/ViewControls";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { getSelectedElementId } from "@/editor/elementId";
import { editorExtensions } from "@/editor/extensions";
import { PX_PER_MM } from "@/editor/pageGeometry";
import { Pagination, REPAGINATE } from "@/editor/pagination";
import { reconcileWithIds, sameContent } from "@/editor/tiptapToDocument";
import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";
import { useFormattingState } from "@/editor/useFormattingState";
import { addElement, addPage, rememberRevision, renameDocument, REVISION_CONFLICT_EVENT, setElementStyle, updateContent } from "@/services/api";
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

const AUTOSAVE_DEBOUNCE_MS = 1200;
// Space between two pages on screen, CSS px (like Word's page view).
const PAGE_GAP_PX = 28;
const CM_TO_PX = 10 * PX_PER_MM;

/** Gives each top-level block the element id it was saved under (new blocks,
 * and the second half of a split, get theirs here), so it stays the same element
 * from one save to the next. Changes attributes only, outside the undo history. */
function syncElementIds(editor: Editor, nodeIds: (string | null)[]) {
  const { tr } = editor.state;
  editor.state.doc.forEach((node, offset, index) => {
    const id = nodeIds[index];
    if (id && node.attrs.elementId !== id) tr.setNodeAttribute(offset, "elementId", id);
  });
  if (tr.docChanged) editor.view.dispatch(tr.setMeta("addToHistory", false));
}

/** Header/footer text with its page-number fields filled in. */
function fillPageFields(text: string, page: number, pages: number): string {
  return text.replaceAll("{PAGE}", String(page)).replaceAll("{NUMPAGES}", String(pages));
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
  // Until the user picks a zoom, pages shrink to fit the column (never grow),
  // so every page's edges stay in view.
  const [chosenZoom, setChosenZoom] = useState<number | null>(null);
  const [fitZoom, setFitZoom] = useState(1);
  const zoom = chosenZoom ?? fitZoom;
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

  // Pagination reads the page geometry from the data-* attributes of the page
  // container below, so the editor never has to be recreated when it changes.
  const extensions = useMemo(() => [...editorExtensions, Pagination.configure({ onPageCount: setPageCount })], []);
  const editor = useEditor({
    extensions,
    content: documentToTiptapJSON(doc),
    immediatelyRender: false,
  });
  useEditorForceUpdate(editor);
  const selectedElementId = editor ? getSelectedElementId(editor) : null;

  const { settings } = doc;
  const heightPx = settings.pageHeightMm * PX_PER_MM;
  const pageWidthPx = settings.pageWidthMm * PX_PER_MM;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const fit = () => {
      const available = canvas.clientWidth - CANVAS_SIDE_PADDING_PX;
      setFitZoom(Math.max(MIN_ZOOM, Math.min(1, available / pageWidthPx)));
    };
    const observer = new ResizeObserver(fit);
    observer.observe(canvas);
    // The observer's first call waits for a rendered frame, which a background tab never gets.
    const initial = setTimeout(fit, 0);
    return () => {
      observer.disconnect();
      clearTimeout(initial);
    };
  }, [pageWidthPx]);
  // New page size or margins: lay the pages out again.
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(REPAGINATE, true));
  }, [editor, heightPx, settings.marginTopCm, settings.marginBottomCm, zoom]);

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

    const tiptapContent = (currentEditor.getJSON().content ?? []) as Parameters<typeof reconcileWithIds>[0];
    const { elements: reconciled, nodeIds } = reconcileWithIds(tiptapContent, docRef.current.elements);
    syncElementIds(currentEditor, nodeIds);
    if (sameContent(reconciled, docRef.current.elements)) {
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

  function applyDocumentUpdate(updated: Document) {
    const previousSelection = editor ? getSelectedElementId(editor) : null;
    docRef.current = updated;
    setDoc(updated);
    editor?.commands.setContent(documentToTiptapJSON(updated));
    if (editor && previousSelection) selectElementById(editor, previousSelection);
  }

  const formatting = useFormattingState(doc, applyDocumentUpdate, flushContent);
  // A formatting job replaces the document when it finishes, so typing meanwhile
  // would be lost: the pages are read-only until it is done.
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.setEditable(!formatting.isApplying, false);
  }, [editor, formatting.isApplying]);

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

  // The Toolbar's alignment buttons outside tables: saved as the selected
  // element's own style (a live override), exactly like the Properties panel.
  async function handleAlign(alignment: string) {
    if (!selectedElementId) return;
    await flushContent();
    applyDocumentUpdate(await setElementStyle(docRef.current.id, selectedElementId, { property: "alignment", value: alignment }));
  }
  const selectedElement = selectedElementId ? doc.elements.find((element) => element.id === selectedElementId) : undefined;
  const selectedAlignment = selectedElement?.styleRef ? (doc.resolvedStyles[selectedElement.styleRef]?.["text-align"] ?? null) : null;

  async function handleRename(title: string) {
    await flushContent();
    applyDocumentUpdate(await renameDocument(docRef.current.id, title));
  }

  function handleFitWidth() {
    const container = canvasRef.current;
    if (!container) return;
    const available = container.clientWidth - CANVAS_SIDE_PADDING_PX;
    setChosenZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, available / pageWidthPx)));
  }

  function handleAiQuickSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aiQuickInput.trim()) return;
    formatting.setInstructionsText(aiQuickInput);
    setAiQuickInput("");
    // Passed along too: the state set just above only arrives with the next render.
    void formatting.handleApply("quick", { instructionsText: aiQuickInput });
  }

  const pageWidth = `${settings.pageWidthMm}mm`;
  const pageStride = heightPx + PAGE_GAP_PX;
  // The editor's own padding is the page margins (see .paged-editor in globals.css),
  // so its first line starts exactly where page 1's text area does.
  const pagedStyle = {
    height: pageCount * pageStride - PAGE_GAP_PX,
    "--page-margin-top": `${settings.marginTopCm}cm`,
    "--page-margin-right": `${settings.marginRightCm}cm`,
    "--page-margin-bottom": `${settings.marginBottomCm}cm`,
    "--page-margin-left": `${settings.marginLeftCm}cm`,
  } as CSSProperties;
  const pageNumberText = (page: number) => (settings.showPageNumbers ? `Page ${page}` : null);

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
      content: <TemplatesPanel state={formatting} documentId={doc.id} documentTitle={doc.metadata.title} />,
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
            <ExportPanel documentId={doc.id} onBeforeExport={flushContent} />
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
            <EditorContextBar editor={editor} alignment={selectedAlignment} onAlign={(alignment) => void handleAlign(alignment)} />
          </div>

          {/* Grey desk behind the pages, as in Word: each page is its own sheet. */}
          <div ref={canvasRef} className="flex-1 overflow-y-auto bg-[#e7e8eb] px-4 py-8 dark:bg-black sm:px-6">
            <p className="mx-auto mb-6 max-w-3xl text-center text-xs text-zinc-500">
              Edits save automatically a moment after you stop typing. Pages are laid out as they print: what doesn&apos;t
              fit on a page continues on the next one.
            </p>

            <div className="mx-auto" style={{ width: pageWidth, zoom }}>
              <div
                className="paged-editor relative"
                style={pagedStyle}
                data-page-height={heightPx}
                data-page-gap={PAGE_GAP_PX}
                data-margin-top={settings.marginTopCm * CM_TO_PX}
                data-margin-bottom={settings.marginBottomCm * CM_TO_PX}
                data-scale={zoom}
              >
                {Array.from({ length: pageCount }, (_, index) => {
                  const header = settings.header ? fillPageFields(settings.header, index + 1, pageCount) : null;
                  const footer = [settings.footer ? fillPageFields(settings.footer, index + 1, pageCount) : null, pageNumberText(index + 1)]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <div
                      key={index}
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-x-0 border border-zinc-300 bg-white shadow-[0_1px_3px_rgba(0,0,0,0.12),0_4px_14px_rgba(0,0,0,0.08)] dark:border-zinc-700 dark:bg-zinc-900"
                      style={{ top: index * pageStride, height: heightPx }}
                    >
                      {header && (
                        <div
                          className="absolute inset-x-0 -translate-y-1/2 truncate text-center text-[11px] text-zinc-500"
                          style={{ top: `${settings.marginTopCm / 2}cm`, paddingLeft: `${settings.marginLeftCm}cm`, paddingRight: `${settings.marginRightCm}cm` }}
                        >
                          {header}
                        </div>
                      )}
                      {footer && (
                        <div
                          className="absolute inset-x-0 translate-y-1/2 truncate text-center text-[11px] text-zinc-500"
                          style={{ bottom: `${settings.marginBottomCm / 2}cm`, paddingLeft: `${settings.marginLeftCm}cm`, paddingRight: `${settings.marginRightCm}cm` }}
                        >
                          {footer}
                        </div>
                      )}
                    </div>
                  );
                })}
                <div ref={paperRef} className="relative z-10 h-full">
                  <EditorContent editor={editor} className="h-full" />
                </div>
              </div>
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
            {formatting.applyingFrom === "quick" && formatting.progress ? (
              <div className="w-44 shrink-0">
                <JobProgressBar progress={formatting.progress} />
              </div>
            ) : (
              <span className="hidden text-xs text-zinc-400 sm:inline">AI помощник</span>
            )}
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
            onZoomChange={setChosenZoom}
            onFitWidth={handleFitWidth}
            pageCount={pageCount}
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
          onResolve={(resolutions) => formatting.handleApply("conflicts", { resolutions })}
          progress={formatting.applyingFrom === "conflicts" ? formatting.progress : null}
        />
      )}

      {showStyleAnalysis && <StyleAnalysisModal document={doc} onClose={() => setShowStyleAnalysis(false)} />}
    </div>
  );
}
