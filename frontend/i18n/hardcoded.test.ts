import { readFileSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * S2-017: the screens moved onto the dictionaries keep no interface English of their own. Literal
 * JSX text and literal aria-label / title / placeholder values are what a person reads; each must come
 * from i18n/messages. Names that are the same in every language (formats, the product) are allowed.
 * The 1.x editor (editor/*) is not listed: it moves to the dictionaries with the 2.0 editor.
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

describe("no hard-coded interface English in the screens on the dictionaries (S2-017)", () => {
  it.each(SCREENS)("%s", (file) => {
    const source = readFileSync(path.resolve(__dirname, "..", file), "utf-8");
    expect(englishIn(file, source)).toEqual([]);
  });
});
