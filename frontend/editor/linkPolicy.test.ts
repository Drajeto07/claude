import { readFileSync } from "node:fs";
import { join } from "node:path";

import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import { editorExtensions } from "./extensions";
import { safeHref } from "./linkPolicy";
import { NOT_KEPT, reconcileWithIds } from "./tiptapToDocument";

/**
 * Which addresses a link may have (SEC-014). The cases are the backend's too
 * (backend/tests/test_link_policy.py reads the same file), so the editor never makes a
 * link the document can't keep, nor drops one it can.
 */
const { cases } = JSON.parse(readFileSync(join(__dirname, "..", "tests", "fixtures", "link-policy.json"), "utf-8")) as {
  cases: [string, string | null][];
};

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function editorWith(content: string): Editor {
  const editor = new Editor({ extensions: editorExtensions, content });
  editors.push(editor);
  return editor;
}

/** The links the editor itself holds -- before the save's own check. */
function links(editor: Editor): string[] {
  const hrefs: string[] = [];
  editor.state.doc.descendants((node) => {
    for (const mark of node.marks) if (mark.type.name === "link") hrefs.push(mark.attrs.href as string);
  });
  return hrefs;
}

describe("the link policy", () => {
  it.each(cases)("answers %j as the backend does", (href, expected) => {
    expect(safeHref(href)).toBe(expected);
  });

  it("makes no link of a pasted address the document can't keep, and keeps the text", () => {
    const editor = editorWith(
      '<p><a href="javascript:alert(1)">run</a> <a href="/wiki/Page">wiki</a> <a href="https://example.com">site</a></p>',
    );
    expect(links(editor)).toEqual(["https://example.com"]);
    expect(editor.getText()).toBe("run wiki site");
  });

  it("names a link it can't keep instead of dropping it silently", () => {
    // As a link could still reach the editor from outside its own parsing.
    const content = [
      { type: "paragraph", content: [{ type: "text", text: "old", marks: [{ type: "link", attrs: { href: "file:///c:/secret.docx" } }] }] },
    ];
    const { elements, notes } = reconcileWithIds(content, []);
    expect(elements[0].inline?.[0].marks).toEqual([]);
    expect(notes).toContain(NOT_KEPT.link);
  });

  it("makes no link of an address too long to follow", () => {
    expect(safeHref(`https://example.com/${"a".repeat(2028)}`)).not.toBeNull(); // 2048 in all
    expect(safeHref(`https://example.com/${"a".repeat(2029)}`)).toBeNull();
  });

  it("gives a bare www. address https://", () => {
    const content = [{ type: "paragraph", content: [{ type: "text", text: "site", marks: [{ type: "link", attrs: { href: "www.example.com" } }] }] }];
    expect(reconcileWithIds(content, []).elements[0].inline?.[0].marks[0].href).toBe("https://www.example.com");
  });
});
