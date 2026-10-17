import { render, screen, within } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";
import type { Locale } from "@/i18n/locales";
import { bg } from "@/i18n/messages/bg";
import { en } from "@/i18n/messages/en";

import { DocumentEditorShell } from "./DocumentEditorShell";
import { EditorToolbar } from "./EditorToolbar";
import { editorExtensions } from "./extensions";

// The shell's own toolbar row is stubbed below; the rich-text toolbar itself is tested as it is.
const { ActualRichTextToolbar } = await vi.importActual<{ RichTextToolbar: typeof import("./RichTextToolbar").RichTextToolbar }>("./RichTextToolbar").then((module) => ({
  ActualRichTextToolbar: module.RichTextToolbar,
}));

// Only the classic editor's own frame is under test: the engine and everything it draws are stand-ins.
const { nothing } = vi.hoisted(() => ({ nothing: () => null }));
vi.mock("@/editor/useEditorEngine", () => ({
  useEditorEngine: () => ({
    document: { id: "doc-1", metadata: { title: "Report" }, elements: [], settings: {}, proposals: [], importReport: null, lastSection: null },
    editor: null,
    page: { zoom: 1, setZoom: () => undefined, fitWidth: () => undefined, pageCount: 1, canvasRef: { current: null } },
    autosave: { status: "saved", problem: null, notKept: [], flush: async () => undefined, retry: () => undefined },
    formatting: { conflicts: null },
    history: {},
    editorState: {},
    changedElsewhere: true,
    actionError: null,
    showHidden: false,
    hiddenWords: 0,
    chrome: [],
  }),
}));
vi.mock("@/editor/EditorState", () => ({
  EditorStateProvider: ({ children }: { children: ReactNode }) => children,
  useDocumentEditor: () => ({ editor: null, selection: { selectedElementId: null, alignment: null }, change: () => undefined }),
}));
vi.mock("@/lib/useMediaQuery", () => ({ useMediaQuery: () => true }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock("@/components/AppHeader", () => ({ AppHeader: nothing }));
vi.mock("@/editor/EditableTitle", () => ({ EditableTitle: nothing }));
vi.mock("@/editor/ExportMenu", () => ({ ExportMenu: nothing }));
vi.mock("@/editor/RichTextToolbar", () => ({ RichTextToolbar: nothing }));
vi.mock("@/editor/EditorCanvas", () => ({ EditorCanvas: nothing }));
vi.mock("@/editor/EditorActionBar", () => ({ EditorActionBar: nothing }));
vi.mock("@/editor/EditorStatusBar", () => ({ EditorStatusBar: nothing }));
vi.mock("@/editor/ConflictModal", () => ({ ConflictModal: nothing }));
vi.mock("@/editor/StyleAnalysisModal", () => ({ StyleAnalysisModal: nothing }));
vi.mock("@/editor/panels/PropertiesSidebar", () => ({ PropertiesSidebar: nothing }));
vi.mock("@/editor/panels/FidelityPanel", () => ({ FidelityPanel: nothing }));
vi.mock("@/editor/panels/HealthPanel", () => ({ HealthPanel: nothing }));
vi.mock("@/editor/panels/ReviewPanel", () => ({ ReviewPanel: nothing }));
vi.mock("@/editor/panels/HistoryPanel", () => ({ HistoryPanel: nothing }));
vi.mock("@/editor/panels/InstructionsPanel", () => ({ InstructionsPanel: nothing }));
vi.mock("@/editor/panels/PageSettingsPanel", () => ({ PageSettingsPanel: nothing }));
vi.mock("@/editor/panels/StructurePanel", () => ({ StructurePanel: nothing }));
vi.mock("@/editor/panels/TemplatesPanel", () => ({ TemplatesPanel: nothing }));
vi.mock("@/editor/panels/TranslatePanel", () => ({ TranslatePanel: nothing }));

function shellIn(locale: Locale) {
  return render(
    <I18nProvider locale={locale}>
      <DocumentEditorShell initialDocument={{} as never} />
    </I18nProvider>,
  );
}

const CASES = {
  en: {
    home: "Home",
    panels: ["Structure", "Templates", "Instructions", "Translate", "Review", "Settings", "History", "Health", "Check"],
    close: "Close Templates",
    banner: "This document was changed in another tab or window",
    reload: "Reload",
    properties: "Properties",
  },
  bg: {
    home: "Начало",
    panels: ["Структура", "Шаблони", "Инструкции", "Превод", "Преглед", "Настройки", "История", "Здраве", "Проверка"],
    close: "Затвори Шаблони",
    banner: "Документът беше променен в друг раздел или прозорец",
    reload: "Презареди",
    properties: "Свойства",
  },
} as const;

describe.each(["en", "bg"] as const)("the classic editor's frame in %s", (locale) => {
  const want = CASES[locale];
  const other = CASES[locale === "en" ? "bg" : "en"];

  it("names every panel, the home link and the open panel in that language only", () => {
    shellIn(locale);
    const rail = screen.getByRole("navigation");
    expect(within(rail).getByRole("link", { name: want.home })).toHaveAttribute("href", "/");
    for (const name of want.panels) expect(within(rail).getByRole("button", { name })).toBeInTheDocument();
    for (const name of other.panels) expect(within(rail).queryByRole("button", { name })).toBeNull();
    // Wide screens open the Templates panel first: its heading, region and close button follow the language.
    expect(screen.getByRole("heading", { name: want.panels[1] })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: want.panels[1] })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: want.close })).toBeInTheDocument();
  });

  it("says a change elsewhere in that language", () => {
    shellIn(locale);
    expect(screen.getByRole("alert")).toHaveTextContent(want.banner);
    expect(screen.getByRole("button", { name: want.reload })).toBeInTheDocument();
  });

  it("names the rich-text tools, font and size in that language", () => {
    const messages = locale === "en" ? en : bg;
    const editor = new Editor({ extensions: editorExtensions, content: "<p>Text</p>" });
    try {
      render(
        <I18nProvider locale={locale}>
          <ActualRichTextToolbar editor={editor} alignment="left" onAlign={() => undefined} />
        </I18nProvider>,
      );
      const { commands } = messages.editorTools;
      for (const name of [commands.undo, commands.bold, commands.italic, commands.alignLeft, commands.alignCenter, commands.bulletList, commands.taskList, commands.clearFormatting]) {
        expect(screen.getByRole("button", { name })).toHaveAttribute("title", name);
      }
      expect(screen.getByRole("combobox", { name: messages.editorTools.font })).toHaveDisplayValue(messages.editorTools.font);
      expect(screen.getByRole("combobox", { name: messages.editorTools.size })).toHaveDisplayValue(messages.editorTools.size);
      expect(screen.getByLabelText(messages.editorTools.textColour, { selector: "input" })).toBeInTheDocument();
    } finally {
      editor.destroy();
    }
  });

  it("names the toolbar's Properties button in that language", () => {
    render(
      <I18nProvider locale={locale}>
        <EditorToolbar onToggleProperties={() => undefined} />
      </I18nProvider>,
    );
    expect(screen.getByRole("button", { name: want.properties })).toHaveAttribute("title", want.properties);
  });
});
