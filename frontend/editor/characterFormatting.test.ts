import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import { editorExtensions } from "./extensions";
import { NOT_KEPT, reconcileWithIds } from "./tiptapToDocument";

/**
 * Word's character formatting in the editor (tracker DOCX-013): underline and
 * strikethrough styles, capitals, small capitals, character spacing and raised or
 * lowered text are read from pasted HTML (Word's own CSS included), drawn with CSS
 * and saved to the Document Model. The golden round trip (editorRoundTrip.test.ts,
 * 02-rich-text) keeps an imported Word file's through the editor.
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

function saved(editor: Editor) {
  return reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], []);
}

function marksOf(editor: Editor): Record<string, Record<string, unknown>> {
  const { elements } = saved(editor);
  return Object.fromEntries(
    (elements[0].inline ?? [])
      .filter((run) => run.marks.length)
      .map((run) => [
        run.text.trim(),
        Object.fromEntries(
          run.marks.flatMap((mark) => Object.entries(mark).filter(([key, value]) => value !== null && key !== "type").map(([key, value]) => [`${mark.type}.${key}`, value])),
        ),
      ]),
  );
}

describe("character formatting in the editor", () => {
  it("reads Word's pasted formatting and saves it", () => {
    const editor = editorWith(
      "<p>" +
        '<u style="text-underline:double">double</u> ' +
        '<u style="text-decoration-style:wavy">wavy</u> ' +
        '<s style="text-decoration-style:double">twice</s> ' +
        '<span style="text-transform:uppercase">shouting</span> ' +
        '<span style="font-variant:small-caps">quiet</span> ' +
        '<span style="letter-spacing:2.0pt">spaced</span> ' +
        '<span style="position:relative;top:-3.0pt">raised</span> ' +
        '<span style="vertical-align:-2pt">lowered</span>' +
        "</p>",
    );

    expect(marksOf(editor)).toEqual({
      double: { "underline.lineStyle": "double" },
      wavy: { "underline.lineStyle": "wavy" },
      twice: { "strike.lineStyle": "double" },
      shouting: { "textStyle.caps": true },
      quiet: { "textStyle.smallCaps": true },
      spaced: { "textStyle.letterSpacingPt": 2 },
      raised: { "textStyle.baselineShiftPt": 3 },
      lowered: { "textStyle.baselineShiftPt": -2 },
    });
  });

  it("draws each with CSS", () => {
    const editor = editorWith(
      '<p><u data-line-style="dotted">dotted</u> <span style="text-transform: uppercase; letter-spacing: 1.5pt; vertical-align: 2pt">styled</span></p>',
    );

    const html = editor.getHTML();
    expect(html).toContain('data-line-style="dotted"');
    expect(html).toContain("text-decoration-style: dotted");
    expect(html).toMatch(/text-transform: uppercase/);
    expect(html).toMatch(/letter-spacing: 1\.5pt/);
    expect(html).toMatch(/vertical-align: 2pt/);
  });

  it("keeps the language text is in, even on a span with nothing else", () => {
    const editor = editorWith('<p><span lang="bg-BG">Добър ден</span> and <span lang="x-none">no language</span></p>');

    expect(marksOf(editor)).toEqual({ "Добър ден": { "textStyle.lang": "bg-BG" } });
    expect(editor.getHTML()).toContain('<span lang="bg-BG">Добър ден</span>');
  });

  it("names spacing it can't keep, and not spacing that is none", () => {
    const em = saved(editorWith('<p><span style="letter-spacing:0.1em">em</span></p>'));
    const none = saved(editorWith('<p><span style="letter-spacing:normal">normal</span> <span style="letter-spacing:0pt">zero</span></p>'));

    expect(em.notes).toContain(NOT_KEPT.spacing);
    expect(none.notes).not.toContain(NOT_KEPT.spacing);
  });
});
