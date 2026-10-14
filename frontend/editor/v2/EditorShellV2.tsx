"use client";

import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CloudOff,
  HeartPulse,
  History,
  Languages,
  LayoutTemplate,
  ListChecks,
  ListTree,
  Loader2,
  Maximize2,
  Menu,
  Minimize2,
  Minus,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Redo2,
  Scan,
  Settings as SettingsIcon,
  ShieldCheck,
  TriangleAlert,
  Undo2,
  Wand2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode, type RefObject } from "react";

import { Logo } from "@/components/ui/Logo";
import { ConflictModal } from "@/editor/ConflictModal";
import { EditableTitle } from "@/editor/EditableTitle";
import { EditorActionBar } from "@/editor/EditorActionBar";
import { EditorCanvas } from "@/editor/EditorCanvas";
import { EditorStateProvider } from "@/editor/EditorState";
import { EditorStatusBar } from "@/editor/EditorStatusBar";
import { ExportMenu } from "@/editor/ExportMenu";
import { FidelityPanel } from "@/editor/panels/FidelityPanel";
import { HealthPanel } from "@/editor/panels/HealthPanel";
import { HistoryPanel } from "@/editor/panels/HistoryPanel";
import { InstructionsPanel } from "@/editor/panels/InstructionsPanel";
import { PageSettingsPanel } from "@/editor/panels/PageSettingsPanel";
import { PropertiesPanel } from "@/editor/panels/PropertiesPanel";
import { ResolvedStylesView } from "@/editor/panels/PropertiesSidebar";
import { ReviewPanel } from "@/editor/panels/ReviewPanel";
import { StructurePanel } from "@/editor/panels/StructurePanel";
import { TemplatesPanel } from "@/editor/panels/TemplatesPanel";
import { TranslatePanel } from "@/editor/panels/TranslatePanel";
import { StyleAnalysisModal } from "@/editor/StyleAnalysisModal";
import type { SaveStatus } from "@/editor/useAutoSave";
import { useEditorEngine } from "@/editor/useEditorEngine";
import { MAX_ZOOM, MIN_ZOOM } from "@/editor/usePageSettings";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { setElementStyle } from "@/services/api";
import type { Document } from "@/types/document";

import { COMMANDS, matchesShortcut, type CommandContext } from "./commands";
import { ContextToolbar } from "./ContextToolbar";
import { selectionOf } from "./selectionModel";
import { usePanelLayout, type PanelId } from "./usePanelLayout";
import { useUnifiedHistory } from "./useUnifiedHistory";

const iconButton =
  "flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-40";
const ZOOM_STEP = 0.1;

/** The save state in words and colour, always in view (architecture §8); a failed save offers to try again. */
function SaveState({ status, onRetry }: { status: SaveStatus; onRetry: () => void }) {
  const { m } = useI18n();
  const t = m.editor2.save;
  const look: Record<SaveStatus, { icon: ReactNode; tone: string }> = {
    idle: { icon: <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />, tone: "text-muted" },
    saved: { icon: <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />, tone: "text-success" },
    saving: { icon: <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />, tone: "text-muted" },
    offline: { icon: <CloudOff className="h-3.5 w-3.5" aria-hidden="true" />, tone: "text-warning" },
    error: { icon: <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />, tone: "text-danger" },
    conflict: { icon: <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />, tone: "text-danger" },
    unsupported: { icon: <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />, tone: "text-danger" },
  };
  const { icon, tone } = look[status];
  return (
    <span role="status" className={`flex shrink-0 items-center gap-1.5 text-xs font-medium ${tone}`}>
      {icon}
      <span className="max-sm:sr-only">{t[status]}</span>
      {status === "error" && (
        <button type="button" onClick={onRetry} className="rounded-md px-1.5 py-0.5 text-accent hover:bg-accent-soft">
          {t.retry}
        </button>
      )}
    </span>
  );
}

/** Which page the reader is on, from where the desk is scrolled; and the way to go to a page. */
function usePageNavigation(canvasRef: RefObject<HTMLDivElement | null>, tops: number[], zoom: number) {
  const [current, setCurrent] = useState(0);
  const offset = () => {
    const canvas = canvasRef.current;
    const pages = canvas?.querySelector<HTMLElement>(".paged-editor");
    if (!canvas || !pages) return 0;
    return pages.getBoundingClientRect().top - canvas.getBoundingClientRect().top + canvas.scrollTop;
  };
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onScroll = () => {
      const line = canvas.scrollTop + canvas.clientHeight / 3 - offset();
      let at = 0;
      tops.forEach((top, index) => {
        if (top * zoom <= line) at = index;
      });
      setCurrent(at);
    };
    onScroll();
    canvas.addEventListener("scroll", onScroll, { passive: true });
    return () => canvas.removeEventListener("scroll", onScroll);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- offset() reads the DOM at scroll time
  }, [canvasRef, tops, zoom]);
  const goTo = (index: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const target = Math.max(0, Math.min(tops.length - 1, index));
    canvas.scrollTo({ top: offset() + tops[target] * zoom - 8, behavior: "smooth" });
  };
  return { current, goTo };
}

/**
 * The SmartDoc 2.0 editor shell (docs/SMARTDOC_2_0_EDITOR_ARCHITECTURE.md, E1 + E2), behind ?editor=2, on the
 * same engine as the classic editor (useEditorEngine). E2: one selection model, a command registry behind the
 * contextual toolbar and the shortcuts, one Undo/Redo over typing and saved changes, panels that hide with one
 * button (Ctrl+\) and remember how they were left, and a phone bar for reading: page x of y, previous/next,
 * zoom and fit width.
 */
export function EditorShellV2({ initialDocument }: { initialDocument: Document }) {
  const { m } = useI18n();
  const t = m.editor2;
  const tools = m.editorTools;
  const engine = useEditorEngine(initialDocument);
  const { document, editor, page, autosave, formatting, history: savedHistory } = engine;
  const history = useUnifiedHistory(engine);
  const wide = useMediaQuery("(min-width: 1100px)");
  const phone = useMediaQuery("(max-width: 639px)");
  const layout = usePanelLayout();
  const [railOpen, setRailOpen] = useState(false);
  const [propertyTab, setPropertyTab] = useState<"edit" | "styles">("edit");
  const [showStyleAnalysis, setShowStyleAnalysis] = useState(false);

  // On wide screens the properties start open; below 1100 px they and the panels open over the pages.
  const showProperties = layout.properties ?? (wide && !layout.hidden);
  const showRail = !layout.hidden && (!phone || railOpen);
  const selection = selectionOf(editor);
  const tops = useMemo(() => page.pages.map((slot) => slot.top), [page.pages]);
  const navigation = usePageNavigation(page.canvasRef, tops, page.zoom);

  const setZoom = (zoom: number) => page.setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(zoom * 100) / 100)));
  const context: CommandContext = {
    editor,
    selection,
    history,
    alignElement: (value) => {
      const id = engine.selection.selectedElementId;
      if (id) void engine.editorState.change((documentId) => setElementStyle(documentId, id, { property: "alignment", value })).catch(() => undefined);
    },
    ui: {
      panelsHidden: layout.hidden,
      togglePanels: layout.togglePanels,
      zoomIn: () => setZoom(page.zoom + ZOOM_STEP),
      zoomOut: () => setZoom(page.zoom - ZOOM_STEP),
      fitWidth: page.fitWidth,
      openProperties: () => layout.setProperties(true),
    },
  };

  // The registry's own shortcuts (undo/redo across both histories, panels, zoom). Typing undo inside the text is
  // the text engine's; an undo that reaches the saved changes, or one pressed outside the text, comes here.
  useEffect(() => {
    const mac = /Mac|iPhone|iPad/.test(navigator.platform);
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select")) return;
      const inText = Boolean(target?.closest(".ProseMirror"));
      for (const command of COMMANDS) {
        if (!command.globalShortcut) continue;
        const keys = [command.shortcut!, ...(command.extraShortcuts ?? [])];
        if (!keys.some((key) => matchesShortcut(event, key, mac))) continue;
        if (command.id === "undo" && inText && history.undoFrom === "typing") return;
        if (command.id === "redo" && inText && history.redoFrom === "typing") return;
        event.preventDefault();
        if (command.isEnabled?.(context) ?? true) void command.run(context);
        return;
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  // "Undone: Template applied" -- for a moment, so an undo of a saved change is never a surprise.
  useEffect(() => {
    if (!history.last) return;
    const timer = window.setTimeout(history.clearLast, 4000);
    return () => window.clearTimeout(timer);
  }, [history.last, history.clearLast]);

  const panels: { id: PanelId; icon: ReactNode; content: ReactNode }[] = [
    { id: "structure", icon: <ListTree className="h-[18px] w-[18px]" aria-hidden="true" />, content: <StructurePanel elements={document.elements} /> },
    { id: "templates", icon: <LayoutTemplate className="h-[18px] w-[18px]" aria-hidden="true" />, content: <TemplatesPanel state={formatting} /> },
    { id: "instructions", icon: <Wand2 className="h-[18px] w-[18px]" aria-hidden="true" />, content: <InstructionsPanel state={formatting} history={savedHistory} showHistory={false} /> },
    { id: "translate", icon: <Languages className="h-[18px] w-[18px]" aria-hidden="true" />, content: <TranslatePanel /> },
    { id: "review", icon: <ListChecks className="h-[18px] w-[18px]" aria-hidden="true" />, content: <ReviewPanel /> },
    { id: "page", icon: <SettingsIcon className="h-[18px] w-[18px]" aria-hidden="true" />, content: <PageSettingsPanel /> },
    { id: "history", icon: <History className="h-[18px] w-[18px]" aria-hidden="true" />, content: <HistoryPanel /> },
    { id: "health", icon: <HeartPulse className="h-[18px] w-[18px]" aria-hidden="true" />, content: <HealthPanel /> },
    { id: "check", icon: <ShieldCheck className="h-[18px] w-[18px]" aria-hidden="true" />, content: <FidelityPanel /> },
  ];
  const open = panels.find((each) => each.id === layout.panel);
  const overlay = !wide ? "absolute inset-y-0 z-30 shadow-pop" : "";
  const undoLabel = history.undoFrom === "saved" ? tools.undoFromSaved : tools.undoFromTyping;
  const redoLabel = history.redoFrom === "saved" ? tools.redoFromSaved : tools.redoFromTyping;
  const percent = Math.round(page.zoom * 100);

  return (
    <EditorStateProvider value={engine.editorState}>
      <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
        {/* Top bar: where you are, the document, whether it's saved, and what applies to the whole document. */}
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-2 sm:gap-3 sm:px-3">
          <Link href="/documents" className={`${iconButton} w-auto gap-1.5 px-2 text-sm`} aria-label={t.projects}>
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            <span className="max-md:hidden">{t.projects}</span>
          </Link>
          {phone && !layout.hidden && (
            <button type="button" onClick={() => setRailOpen(!railOpen)} aria-expanded={railOpen} aria-label={t.panelsNav} className={iconButton}>
              <Menu className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          <span className="h-6 w-px bg-line max-sm:hidden" aria-hidden="true" />
          <span className="max-lg:hidden">
            <Logo />
          </span>
          <div className="min-w-0 flex-1 overflow-hidden">
            <EditableTitle title={document.metadata.title} onRename={(title) => void engine.rename(title)} />
          </div>
          <SaveState status={autosave.status} onRetry={autosave.retry} />
          <span className="flex items-center max-sm:hidden">
            <button type="button" onClick={() => void history.undo()} disabled={!history.canUndo} aria-label={undoLabel} title={`${undoLabel} (Ctrl+Z)`} className={iconButton}>
              <Undo2 className="h-4 w-4" aria-hidden="true" />
            </button>
            <button type="button" onClick={() => void history.redo()} disabled={!history.canRedo} aria-label={redoLabel} title={`${redoLabel} (Ctrl+Shift+Z)`} className={iconButton}>
              <Redo2 className="h-4 w-4" aria-hidden="true" />
            </button>
          </span>
          <Link
            href={`/documents/${document.id}`}
            title={t.classic}
            className="shrink-0 rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-semibold text-accent hover:brightness-95 max-lg:hidden"
          >
            {t.badge}
          </Link>
          <button
            type="button"
            onClick={layout.togglePanels}
            aria-pressed={layout.hidden}
            aria-label={layout.hidden ? tools.showPanels : tools.hidePanels}
            title={`${layout.hidden ? tools.showPanels : tools.hidePanels} (Ctrl+\\)`}
            className={iconButton}
          >
            {layout.hidden ? <Minimize2 className="h-4 w-4" aria-hidden="true" /> : <Maximize2 className="h-4 w-4" aria-hidden="true" />}
          </button>
          {!layout.hidden && (
            <button
              type="button"
              onClick={() => layout.setProperties(!showProperties)}
              aria-pressed={showProperties}
              aria-label={showProperties ? t.hideProperties : t.showProperties}
              title={showProperties ? t.hideProperties : t.showProperties}
              className={`${iconButton} max-sm:hidden`}
            >
              {showProperties ? <PanelRightClose className="h-4 w-4" aria-hidden="true" /> : <PanelRightOpen className="h-4 w-4" aria-hidden="true" />}
            </button>
          )}
          <ExportMenu documentId={document.id} flush={autosave.flush} />
        </header>

        {engine.changedElsewhere && (
          <div role="alert" className="flex items-center justify-between gap-4 border-b border-warning/40 bg-warning-soft px-4 py-2 text-sm text-foreground">
            <span>{t.changedElsewhere}</span>
            <button type="button" onClick={() => window.location.reload()} className="shrink-0 rounded-full bg-warning px-3 py-1 text-xs font-medium text-surface">
              {t.reload}
            </button>
          </div>
        )}

        <div className="relative flex min-h-0 flex-1">
          {/* Rail: one button per panel; the open one sits beside it. */}
          {showRail && (
            <nav
              aria-label={t.panelsNav}
              className={`flex w-[84px] shrink-0 flex-col items-center gap-1 overflow-y-auto border-r border-line bg-surface py-2 ${phone ? "absolute inset-y-0 left-0 z-40 shadow-pop" : ""}`}
            >
              {panels.map((each) => {
                const label = t.panels[each.id];
                const active = layout.panel === each.id;
                return (
                  <button
                    key={each.id}
                    type="button"
                    onClick={() => {
                      layout.setPanel(active ? null : each.id);
                      setRailOpen(false);
                    }}
                    aria-pressed={active}
                    aria-label={format(t.openPanel, { panel: label })}
                    className={`flex w-[76px] flex-col items-center gap-0.5 rounded-xl px-1 py-1.5 text-[10.5px] font-medium leading-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                      active ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-muted hover:text-foreground"
                    }`}
                  >
                    {each.icon}
                    <span className="w-full truncate text-center">{label}</span>
                  </button>
                );
              })}
            </nav>
          )}

          {open && (
            <aside aria-label={t.panels[open.id]} className={`flex w-72 shrink-0 flex-col border-r border-line bg-surface ${overlay} ${phone ? "left-0 max-w-[90vw]" : "left-[84px]"}`}>
              <div className="flex h-11 items-center justify-between border-b border-line px-4">
                <h2 className="text-sm font-semibold text-foreground">{t.panels[open.id]}</h2>
                <button type="button" onClick={() => layout.setPanel(null)} aria-label={t.closePanel} className={iconButton}>
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">{open.content}</div>
            </aside>
          )}

          {/* The working area: the tools for the selection, then the pages, as wide as the panels leave. */}
          <main aria-label={t.canvas} className="relative flex min-w-0 flex-1 flex-col bg-surface-muted">
            <div className="shrink-0 px-2 pt-2 sm:px-3 sm:pt-3">
              <ContextToolbar context={context} />
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
              paper
            />
            {history.last && (
              <p role="status" className="pointer-events-none absolute bottom-16 left-1/2 z-20 -translate-x-1/2 rounded-full bg-foreground px-4 py-2 text-sm text-background shadow-pop sm:bottom-24">
                {format(history.last.kind === "undone" ? tools.undone : tools.redone, { what: history.last.what })}
              </p>
            )}
            {(engine.actionError || history.error) && (
              <div role="alert" className="flex items-center justify-between gap-3 border-t border-danger/30 bg-danger/5 px-4 py-2 text-sm text-danger">
                <span>{engine.actionError ?? history.error}</span>
                <button type="button" onClick={engine.clearActionError} aria-label={t.dismiss} className="shrink-0">
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            )}
            {/* The 1.x action bar (AI helper, style check, add element) keeps its place on larger screens; on a
                phone the pages come first (phones are read-mostly in the first release, plan section 3). */}
            <div className="max-sm:hidden">
              <EditorActionBar
                formatting={formatting}
                onAnalyzeStyle={() => setShowStyleAnalysis(true)}
                onAddElement={(type) => void engine.addElementAfterSelection(type)}
                onSaveNow={autosave.retry}
              />
            </div>
            <div className="max-sm:hidden">
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
            {/* Phones: reading first -- which page, previous/next, zoom and fit width, in reach of a thumb. */}
            <nav aria-label={t.canvas} className="flex h-12 shrink-0 items-center justify-between gap-1 border-t border-line bg-surface px-2 sm:hidden">
              <span className="flex items-center">
                <button type="button" onClick={() => navigation.goTo(navigation.current - 1)} disabled={navigation.current === 0} aria-label={tools.previousPage} className={iconButton}>
                  <ChevronUp className="h-4 w-4" aria-hidden="true" />
                </button>
                <span className="min-w-16 text-center text-xs font-medium text-foreground" aria-live="polite">
                  {format(tools.page, { current: navigation.current + 1, total: page.pageCount })}
                </span>
                <button
                  type="button"
                  onClick={() => navigation.goTo(navigation.current + 1)}
                  disabled={navigation.current >= page.pageCount - 1}
                  aria-label={tools.nextPage}
                  className={iconButton}
                >
                  <ChevronDown className="h-4 w-4" aria-hidden="true" />
                </button>
              </span>
              <span className="flex items-center">
                <button type="button" onClick={context.ui.zoomOut} aria-label={tools.commands.zoomOut} className={iconButton}>
                  <Minus className="h-4 w-4" aria-hidden="true" />
                </button>
                <span className="w-12 text-center text-xs tabular-nums text-muted" aria-label={format(tools.zoom, { percent })}>
                  {percent}%
                </span>
                <button type="button" onClick={context.ui.zoomIn} aria-label={tools.commands.zoomIn} className={iconButton}>
                  <Plus className="h-4 w-4" aria-hidden="true" />
                </button>
                <button type="button" onClick={page.fitWidth} aria-label={tools.commands.fitWidth} className={iconButton}>
                  <Scan className="h-4 w-4" aria-hidden="true" />
                </button>
              </span>
            </nav>
          </main>

          {showProperties && (
            <aside aria-label={t.properties} className={`right-0 flex w-64 shrink-0 flex-col border-l border-line bg-surface ${overlay}`}>
              <div role="tablist" aria-label={t.properties} className="flex h-11 items-stretch border-b border-line">
                {(["edit", "styles"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={propertyTab === tab}
                    onClick={() => setPropertyTab(tab)}
                    className={`flex-1 border-b-2 px-3 text-sm font-medium transition-colors ${propertyTab === tab ? "border-accent text-accent" : "border-transparent text-muted hover:text-foreground"}`}
                  >
                    {t.propertyTabs[tab]}
                  </button>
                ))}
                {!wide && (
                  <button type="button" onClick={() => layout.setProperties(false)} aria-label={t.hideProperties} className="px-3 text-muted hover:text-foreground">
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                )}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">{propertyTab === "edit" ? <PropertiesPanel /> : <ResolvedStylesView />}</div>
            </aside>
          )}
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
