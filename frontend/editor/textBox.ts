import { mergeAttributes, Node } from "@tiptap/core";

import type { Element } from "@/types/document";

/**
 * A Word text box in the editor (tracker DOCX-019A): a box holding its own blocks, drawn
 * with its width, outline, fill and insets. Its look rides on the node as `textBox` (the
 * server's TextBoxContent, saved back as it came); one that floats to a side has the text
 * after it laid beside it by editor/floatWrap.ts, as a floating picture does.
 */

export type TextBoxLook = NonNullable<Element["textBox"]>;

const WORD_LINE = "solid 0.5pt #000000"; // Word's own outline for a box with none set

/** The box's style: its width (never wider than the column), outline, fill and insets. */
export function textBoxStyle(box: TextBoxLook | null | undefined): string {
  const style: string[] = ["box-sizing:border-box", "max-width:100%"];
  if (box?.widthCm) style.push(`width:${box.widthCm}cm`);
  const border = box?.border ?? WORD_LINE;
  if (border === "none") style.push("border:none");
  else {
    const [kind, width, color] = border.split(/\s+/);
    style.push(`border:${width ?? "0.5pt"} ${kind === "double" || kind === "dotted" || kind === "dashed" ? kind : "solid"} ${color ?? "#000000"}`);
  }
  if (box?.fill) style.push(`background-color:${box.fill}`);
  const inset = (value: number | null | undefined, word: number) => `${value ?? word}cm`;
  const insets = box?.insets;
  style.push(
    `padding:${inset(insets?.topCm, 0.13)} ${inset(insets?.rightCm, 0.25)} ${inset(insets?.bottomCm, 0.13)} ${inset(insets?.leftCm, 0.25)}`,
  );
  return style.join(";");
}

export const TextBox = Node.create({
  name: "textBox",
  group: "block",
  content: "block+",
  defining: true,
  isolating: true,

  addAttributes() {
    return { textBox: { default: null, rendered: false } };
  },

  parseHTML() {
    return [{ tag: 'div[data-type="text-box"]' }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "text-box", class: "text-box", style: textBoxStyle(node.attrs.textBox as TextBoxLook | null) }), 0];
  },
});
