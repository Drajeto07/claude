import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * S2-017: the screens moved onto the dictionaries keep no interface English of their own. Literal
 * JSX text and literal aria-label / title / placeholder values are what a person reads; each must come
 * from i18n/messages. Names that are the same in every language (formats, the product) are allowed.
 * The editor's bars, dialogs and panels are listed since E2 (shared by the classic and the 2.0 editor);
 * the classic shell's own frame (its rail, banner and toolbar button) since Stage 1, with no Bulgarian
 * of its own either (CLASSIC_FRAME below).
 */
const SCREENS = [
  "components/AccountMenu.tsx",
  "components/AccountSettings.tsx",
  "components/AppHeader.tsx",
  "components/ConfirmDialog.tsx",
  "components/JobProgressBar.tsx",
  "components/Landing.tsx",
  "components/PasswordResetForms.tsx",
  "components/PlanLimitBanner.tsx",
  "components/ReferenceStyleSummary.tsx",
  "components/TrackedChangesChoice.tsx",
  "components/VerifyEmail.tsx",
  "components/billing/BillingPage.tsx",
  "components/documents/BatchBar.tsx",
  "components/documents/CompareView.tsx",
  "components/documents/DocumentList.tsx",
  "components/templates/TemplateLibrary.tsx",
  "components/templates/TemplateEditor.tsx",
  "components/templates/TemplateHistory.tsx",
  "components/templates/StyleSystemForm.tsx",
  "components/templates/fields.tsx",
  "components/templates/StylePreviewPage.tsx",
  "components/dashboard/Dashboard.tsx",
  "components/dashboard/ProjectCard.tsx",
  "components/shell/AppShell.tsx",
  "components/projects/create/AddContent.tsx",
  "components/projects/create/ChooseLook.tsx",
  "components/projects/create/DocumentFlow.tsx",
  "components/projects/create/ProcessingView.tsx",
  "components/projects/create/StructureReview.tsx",
  "components/SidePanel.tsx",
  "editor/AddElementMenu.tsx",
  "editor/ConflictModal.tsx",
  "editor/DocumentEditorShell.tsx",
  "editor/EditorCanvas.tsx",
  "editor/EditorToolbar.tsx",
  "editor/EditableTitle.tsx",
  "editor/EditorActionBar.tsx",
  "editor/EditorStatusBar.tsx",
  "editor/ExportMenu.tsx",
  "editor/RichTextToolbar.tsx",
  "editor/StyleAnalysisModal.tsx",
  "editor/v2/ContextToolbar.tsx",
  "editor/v2/EditorShellV2.tsx",
  "editor/panels/CleanCopySection.tsx",
  "editor/panels/DoctorPanel.tsx",
  "editor/panels/FidelityPanel.tsx",
  "editor/panels/HealthPanel.tsx",
  "editor/panels/HistoryPanel.tsx",
  "editor/panels/InstructionsPanel.tsx",
  "editor/panels/PageSettingsPanel.tsx",
  "editor/panels/PictureControls.tsx",
  "editor/panels/PropertiesPanel.tsx",
  "editor/panels/PropertiesSidebar.tsx",
  "editor/panels/ProposalsList.tsx",
  "editor/panels/RepairSection.tsx",
  "editor/panels/ReviewPanel.tsx",
  "editor/panels/StructurePanel.tsx",
  "editor/panels/TemplatesPanel.tsx",
  "editor/panels/TranslatePanel.tsx",
];

// The same in both languages: file formats, page sizes, the product.
const ALLOWED = new Set(["Word", "PDF", "A4", "Letter", "Legal", "SmartDoc"]);

const READ_ATTRIBUTES = new Set(["aria-label", "title", "placeholder", "alt"]);

/** What a person would read, written in the file itself: JSX text, and literal readable attributes
 * (found with the TypeScript parser, so generics and comparisons are never mistaken for text). */
function englishIn(file: string, source: string): string[] {
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      const text = node.text.replace(/\s+/g, " ").trim();
      // Sample page content is Bulgarian on purpose (it shows whether a font has Cyrillic), not interface text.
      if (/[A-Za-z]{2,}/.test(text) && !/[а-яА-Я]/.test(text) && !ALLOWED.has(text)) found.push(text);
    } else if (ts.isJsxAttribute(node) && READ_ATTRIBUTES.has(node.name.getText()) && node.initializer && ts.isStringLiteral(node.initializer)) {
      const value = node.initializer.text;
      if (/[A-Za-z]{2,}/.test(value) && !ALLOWED.has(value)) found.push(`${node.name.getText()}="${value}"`);
    }
    ts.forEachChild(node, visit);
  };
  visit(ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX));
  return found;
}

/** Every .ts/.tsx under a folder, tests left out. */
function sources(folder: string): string[] {
  const root = path.resolve(__dirname, "..", folder);
  return (readdirSync(root, { recursive: true }) as string[])
    .filter((file) => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file))
    .map((file) => path.join(folder, file));
}

describe("the screens use the light/dark tokens, not the 1.x palette (S2-R06)", () => {
  it.each(["components", "app", "editor"])("%s has no zinc-* classes", (folder) => {
    const offenders = sources(folder).filter((file) => readFileSync(path.resolve(__dirname, "..", file), "utf-8").includes("zinc-"));
    expect(offenders).toEqual([]);
  });
});

describe("no hard-coded interface English in the screens on the dictionaries (S2-017)", () => {
  it.each(SCREENS)("%s", (file) => {
    const source = readFileSync(path.resolve(__dirname, "..", file), "utf-8");
    expect(englishIn(file, source)).toEqual([]);
  });
});

// The classic editor's frame used to name its panels in Bulgarian whatever the interface language (Stage 1).
const CLASSIC_FRAME = ["components/SidePanel.tsx", "editor/DocumentEditorShell.tsx", "editor/EditorToolbar.tsx", "editor/RichTextToolbar.tsx", "editor/EditorCanvas.tsx"];

/** Bulgarian written in the file itself: JSX text and string literals (comments are not looked at). */
function bulgarianIn(file: string, source: string): string[] {
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node) || ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      const text = node.text.replace(/\s+/g, " ").trim();
      if (/[а-яА-Я]/.test(text)) found.push(text);
    }
    ts.forEachChild(node, visit);
  };
  visit(ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX));
  return found;
}

describe("no hard-coded interface Bulgarian in the classic editor's frame (Stage 1)", () => {
  it.each(CLASSIC_FRAME)("%s", (file) => {
    const source = readFileSync(path.resolve(__dirname, "..", file), "utf-8");
    expect(bulgarianIn(file, source)).toEqual([]);
  });
});
