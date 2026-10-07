import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";

import { shiftedMargin } from "@/editor/sectionPages";

import type { PictureAttr } from "./pictureLook";
import type { TextBoxLook } from "./textBox";

/**
 * A floating picture with the text beside it on the editor's pages (tracker DOCX-018A).
 * The paged editor is a flex column (its block margins add up, which pagination relies
 * on), where CSS floats don't apply, so the wrap is laid out here instead: the text
 * blocks after a picture that floats to a side (placement.side, worked out at import)
 * move over by its width and Word's distance to the text, the first of them up beside
 * the picture's top, until they reach its bottom; whatever comes after starts below it.
 * Text wraps beside the picture block by block -- a block that runs past the picture's
 * bottom stays narrowed to its end, where Word wraps the lines under it -- and stops at a
 * table, a picture, a break or a page break. A PDF wraps line by line (export/pdf_export.py).
 */

type Layout = { from: number; to: number; style: string; push?: number }[];

export const floatWrapKey = new PluginKey<DecorationSet>("floatWrap");

const WRAPS = new Set(["paragraph", "heading", "bulletList", "orderedList", "taskList", "blockquote", "codeBlock", "caption", "footnote"]);
const LAYOUT_DELAY_MS = 40;

export const FloatWrap = Extension.create({
  name: "floatWrap",
  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: floatWrapKey,
        state: {
          init: () => DecorationSet.empty,
          apply(tr, set) {
            const layout = tr.getMeta(floatWrapKey) as Layout | undefined;
            if (layout) return DecorationSet.create(tr.doc, layout.map(({ from, to, style, push }) => Decoration.node(from, to, { style }, { wrap: style, push: push ?? 0 })));
            return set.map(tr.mapping, tr.doc);
          },
        },
        props: { decorations: (state) => floatWrapKey.getState(state) },
        view: (view) => new FloatWrapper(view),
      }),
    ];
  },
});

function sideOf(node: ProseMirrorNode): "left" | "right" | null {
  if (node.type.name === "textBox") return ((node.attrs.textBox ?? null) as TextBoxLook | null)?.placement?.side ?? null; // DOCX-019A
  if (node.type.name !== "image") return null;
  return ((node.attrs.picture ?? null) as PictureAttr | null)?.placement?.side ?? null;
}

function px(value: string): number {
  const number = parseFloat(value);
  return Number.isFinite(number) ? number : 0;
}

class FloatWrapper {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly observer: ResizeObserver;

  constructor(private readonly view: EditorView) {
    this.observer = new ResizeObserver(() => this.schedule());
    this.observer.observe(view.dom);
    view.dom.addEventListener("load", this.schedule, true);
    this.schedule();
  }

  update() {
    this.schedule();
  }

  destroy() {
    clearTimeout(this.timer);
    this.observer.disconnect();
    this.view.dom.removeEventListener("load", this.schedule, true);
  }

  readonly schedule = () => {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.layout(), LAYOUT_DELAY_MS);
  };

  private layout() {
    const { view } = this;
    if (!view.dom.isConnected) return;
    const scale = Number(view.dom.closest<HTMLElement>("[data-page-height]")?.dataset.scale) || 1;
    const nodes: { node: ProseMirrorNode; pos: number }[] = [];
    view.state.doc.forEach((node, pos) => nodes.push({ node, pos }));
    const layout: Layout = [];
    // What the last layout pushed down, by position: a block's own top margin is what it has without it.
    const pushed = new Map<number, number>();
    for (const decoration of floatWrapKey.getState(view.state)?.find() ?? []) pushed.set(decoration.from, (decoration.spec as { push?: number }).push ?? 0);
    for (let index = 0; index < nodes.length; index += 1) {
      const side = sideOf(nodes[index].node);
      const picture = view.nodeDOM(nodes[index].pos);
      if (!side || !(picture instanceof HTMLElement)) continue;
      const own = getComputedStyle(picture);
      const box = picture.getBoundingClientRect();
      const width = box.width / scale + px(side === "left" ? own.marginRight : own.marginLeft);
      const height = box.height / scale + px(own.marginBottom); // from its top to where text below may start
      let covered = 0; // how far down the picture the blocks beside it reach
      let next = index + 1;
      for (; next < nodes.length && covered < height; next += 1) {
        const { node, pos } = nodes[next];
        const dom = view.nodeDOM(pos);
        if (!WRAPS.has(node.type.name) || !(dom instanceof HTMLElement) || dom.previousElementSibling?.classList.contains("page-spacer")) break;
        const css = getComputedStyle(dom);
        const style = String(node.attrs.style ?? "");
        const first = next === index + 1;
        const outer = dom.getBoundingClientRect().height / scale + px(css.marginBottom) + (first ? 0 : px(css.marginTop) - (pushed.get(pos) ?? 0));
        const parts = [`margin-${side}:${shiftedMargin(style, side, Math.round(width))}`];
        if (first) parts.push(`margin-top:${-Math.round(height)}px`); // up beside the picture's top
        layout.push({ from: pos, to: pos + node.nodeSize, style: parts.join(";") });
        covered += outer;
      }
      if (next < nodes.length && covered < height && next > index + 1) {
        // What comes after the blocks beside it starts below the picture.
        const { node, pos } = nodes[next];
        const dom = view.nodeDOM(pos);
        const top = dom instanceof HTMLElement ? px(getComputedStyle(dom).marginTop) - (pushed.get(pos) ?? 0) : 0;
        const push = Math.round(height - covered);
        layout.push({ from: pos, to: pos + node.nodeSize, style: `margin-top:${Math.round(top) + push}px`, push });
      }
      index = next - 1;
    }
    const current = (floatWrapKey.getState(view.state)?.find() ?? []).map((decoration) => `${decoration.from}:${(decoration.spec as { wrap?: string }).wrap}`);
    const wanted = layout.map(({ from, style }) => `${from}:${style}`);
    if (current.length !== wanted.length || current.some((entry, at) => entry !== wanted[at])) {
      view.dispatch(view.state.tr.setMeta(floatWrapKey, layout).setMeta("addToHistory", false));
    }
  }
}
