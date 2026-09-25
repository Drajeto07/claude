import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { Editor } from "@tiptap/react";
import { describe, expect, it } from "vitest";

import type { Document, Element } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { reconcileElements, sameContent } from "./tiptapToDocument";

/**
 * корекции.docx §45 on the editor's side: a real Word document, as the importer
 * reads it (tests/fixtures/golden/, written by the backend's
 * scripts/export_golden_json.py), shown in the real editor and read back the
 * way autosave does must be the same document -- nothing lost or changed just
 * by opening and saving it.
 */
// The tests run from the frontend folder (npm test).
const GOLDEN = path.join(process.cwd(), "tests", "fixtures", "golden");
const NAMES = readdirSync(GOLDEN).filter((name) => name.endsWith(".json"));

function load(name: string): Document {
  return JSON.parse(readFileSync(path.join(GOLDEN, name), "utf8")) as Document;
}

/** The elements autosave would send after the document was opened, untouched. */
function throughTheEditor(document: Document): Element[] {
  const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
  try {
    return reconcileElements((editor.getJSON().content ?? []) as Record<string, unknown>[], document.elements);
  } finally {
    editor.destroy();
  }
}

/** A value with null, absent and empty-list fields dropped, as sameContent compares them -- for readable diffs. */
function plain(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== null && item !== undefined && !(Array.isArray(item) && item.length === 0))
        .map(([key, item]) => [key, plain(item)]),
    );
  }
  return value;
}

describe("golden documents through the editor", () => {
  it("has the whole golden set", () => {
    expect(NAMES).toHaveLength(12);
  });

  it.each(NAMES)("%s comes back from the editor unchanged", (name) => {
    const document = load(name);
    const original = [...document.elements].sort((a, b) => a.order - b.order);

    const saved = throughTheEditor(document);

    expect(saved.map((element) => element.id)).toEqual(original.map((element) => element.id));
    saved.forEach((element, index) => {
      if (!sameContent(element, original[index])) expect(plain(element)).toEqual(plain(original[index]));
    });
  });

  it("keeps an edit and nothing else", () => {
    const document = load("12-complex.json");
    const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
    try {
      editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize - 1); // the end of the first block
      editor.commands.insertContent(" (draft)");
      const saved = reconcileElements((editor.getJSON().content ?? []) as Record<string, unknown>[], document.elements);

      expect(saved[0].content).toBe(`${document.elements[0].content} (draft)`);
      saved.slice(1).forEach((element, index) => {
        if (!sameContent(element, document.elements[index + 1])) expect(plain(element)).toEqual(plain(document.elements[index + 1]));
      });
    } finally {
      editor.destroy();
    }
  });
});
