import { fireEvent, render, screen } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Element, InlineRun } from "@/types/document";

import { EditorStatusBar } from "./EditorStatusBar";
import { editorExtensions } from "./extensions";
import { hiddenWordCount, visibleText } from "./hiddenText";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * Word's hidden text in the editor (tracker DOCX-025): kept with its mark, drawn
 * hidden (globals.css shows it only under .show-hidden), never spreading to what
 * is typed next to it, and shown on request from the status bar. The golden round
 * trip (editorRoundTrip.test.ts, 02-rich-text) keeps it through the editor.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function editorWith(content: string): Editor {
  const editor = new Editor({ extensions: editorExtensions, content });
  editors.push(editor);
  return editor;
}

function runs(editor: Editor): [string, string[]][] {
  const { elements } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], []);
  return (elements[0].inline ?? []).map((run) => [run.text, run.marks.map((mark) => mark.type)]);
}

describe("hidden text in the editor", () => {
  it("is drawn as hidden text and saved with its mark", () => {
    const editor = editorWith('<p>Seen <span data-hidden="">unseen</span> again</p>');

    expect(editor.getHTML()).toContain('<span data-hidden="" class="hidden-text">unseen</span>');
    expect(runs(editor)).toEqual([
      ["Seen ", []],
      ["unseen", ["hidden"]],
      [" again", []],
    ]);
  });

  it("doesn't hide what is typed right after it", () => {
    const editor = editorWith('<p>Seen <span data-hidden="">unseen</span></p>');
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);

    editor.view.dispatch(editor.state.tr.insertText(" typed"));

    expect(runs(editor)).toEqual([
      ["Seen ", []],
      ["unseen", ["hidden"]],
      [" typed", []],
    ]);
  });

  it("stays hidden when pasted from Word (display: none)", () => {
    const editor = editorWith('<p>Visible <span style="display:none;mso-hide:all">secret</span></p>');

    expect(runs(editor)).toEqual([
      ["Visible ", []],
      ["secret", ["hidden"]],
    ]);
  });
});

describe("hiddenWordCount", () => {
  const unset = { href: null, title: null, lineStyle: null, fontFamily: null, fontSizePt: null, color: null, backgroundColor: null, caps: null, smallCaps: null, letterSpacingPt: null, baselineShiftPt: null, lang: null };
  const hidden = (text: string): InlineRun => ({ text, marks: [{ type: "hidden", ...unset }] });
  const block = (inline: InlineRun[], extra: Partial<Element> = {}) => ({ id: "x", type: "paragraph", content: "", inline, ...extra }) as unknown as Element;

  it("counts hidden words in paragraphs, list items, table cells and nested blocks", () => {
    const elements = [
      block([{ text: "shown", marks: [] }, hidden("two words")]),
      block([], { type: "list", listItems: [{ id: "i", inline: [hidden("one")], blocks: [block([hidden("nested three words")])] }] } as Partial<Element>),
      block([], { type: "table", table: { rows: [{ id: "r", cells: [{ id: "c", inline: [hidden("cell")], blocks: null }] }] } } as unknown as Partial<Element>),
    ];

    expect(hiddenWordCount(elements)).toBe(2 + 1 + 3 + 1);
  });

  it("leaves hidden text out of what an outline shows", () => {
    expect(visibleText(block([{ text: "Results", marks: [] }, hidden(" (draft)")]))).toBe("Results");
    expect(visibleText({ ...block([]), inline: null, content: "Plain" } as unknown as Element)).toBe("Plain");
  });
});

describe("the status bar's hidden text switch", () => {
  const props = {
    zoom: 1,
    onZoomChange: () => {},
    onFitWidth: () => {},
    pageCount: 1,
    onAddPage: () => {},
    saveStatus: "saved" as const,
    onRetrySave: () => {},
  };

  it("shows only when the document has hidden text, and says how much", () => {
    const { rerender } = render(<EditorStatusBar {...props} hiddenWords={0} />);
    expect(screen.queryByRole("button", { name: /hidden text/ })).toBeNull();

    const toggle = vi.fn();
    rerender(<EditorStatusBar {...props} hiddenWords={6} onToggleHidden={toggle} />);
    const button = screen.getByRole("button", { name: "Show hidden text (6 words)" });
    expect(button).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(button);
    expect(toggle).toHaveBeenCalledTimes(1);

    rerender(<EditorStatusBar {...props} hiddenWords={6} showHidden onToggleHidden={toggle} />);
    expect(screen.getByRole("button", { name: "Hide hidden text" })).toHaveAttribute("aria-pressed", "true");
  });
});
