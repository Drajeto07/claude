import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, type EditorState } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";

import { blockDoms } from "@/editor/blockDom";
import { columnShift, sectionPage, shiftedMargin, type PageBox, type PageSlot } from "@/editor/sectionPages";
import { layoutDelay, noteTyping } from "./textEdit";

/**
 * Real pages in the editor. The document is still one editable flow, but it is
 * laid out onto separate pages: a block that doesn't fit in what's left of a
 * page moves to the next one, and a page break starts a new page. It works by
 * measuring each block after every change and putting an invisible spacer in
 * front of the ones that have to move (spacers are decorations: they never
 * reach the saved document).
 *
 * Each section's pages have its own size, orientation and margins (DOCX-015,
 * editor/sectionPages.ts): a page is in the section of the block it begins with,
 * and a section whose text column isn't the document's has its blocks widened or
 * narrowed to it (margin decorations over their own margins).
 *
 * A list moves item by item, so a long list continues on the next page. A single
 * block taller than a whole page (a very long table, say) can't be split and
 * runs past the page edge.
 */

type Geometry = {
  /** The document's own page (the last section's), CSS px. */
  base: PageBox;
  /** Space between two pages, CSS px. */
  gap: number;
  /** The CSS zoom the editor is shown at (measurements come back zoomed). */
  scale: number;
};

type Spacer = { pos: number; height: number };
type Shift = { from: number; to: number; style: string };
type Layout = { spacers: Spacer[]; shifts: Shift[] };

const LIST_TYPES = new Set(["bulletList", "orderedList", "taskList"]);
const SPACER_TOLERANCE_PX = 1;

export const paginationKey = new PluginKey<DecorationSet>("pagination");

export type PaginationOptions = {
  /** Every page as laid out: where it starts, its section and its size and margins (DOCX-015). */
  onPages: (pages: PageSlot[]) => void;
};

/**
 * The page geometry, read from the element that lays the pages out: it carries
 * the document's page -- data-page-width, data-page-height, data-margin-top,
 * -bottom, -left, -right, data-header-distance, data-footer-distance (CSS px) --
 * data-page-gap and data-scale (the zoom), so the layout always matches what is
 * on screen. Each section's page is worked out from it and its section break.
 */
function geometryOf(view: EditorView): Geometry | null {
  const container = view.dom.closest<HTMLElement>("[data-page-height]");
  if (!container) return null;
  const value = (name: string) => Number(container.dataset[name]);
  const base: PageBox = {
    width: value("pageWidth"),
    height: value("pageHeight"),
    marginTop: value("marginTop"),
    marginBottom: value("marginBottom"),
    marginLeft: value("marginLeft"),
    marginRight: value("marginRight"),
    headerDistance: value("headerDistance"),
    footerDistance: value("footerDistance"),
  };
  const gap = value("pageGap");
  const scale = value("scale") || 1;
  return [...Object.values(base), gap].every(Number.isFinite) && base.height > 0 ? { base, gap, scale } : null;
}

/** Where the last section's page numbers restart (Document.lastSection, which no section
 * break holds): the page container's data-last-section-start, when it has one. */
function lastSectionRestart(view: EditorView): number | null {
  const value = view.dom.closest<HTMLElement>("[data-page-height]")?.dataset.lastSectionStart;
  return value ? Number(value) : null;
}

/** Meta for a transaction that only asks for the pages to be laid out again
 * (after the page size or margins changed, say). */
export const REPAGINATE = "repaginate";

export const Pagination = Extension.create<PaginationOptions>({
  name: "pagination",

  addOptions() {
    return { onPages: () => undefined };
  },

  addProseMirrorPlugins() {
    const options = this.options;
    return [
      new Plugin<DecorationSet>({
        key: paginationKey,
        state: {
          init: () => DecorationSet.empty,
          apply(tr, set, _old, state) {
            noteTyping(tr, state);
            const layout = tr.getMeta(paginationKey) as Layout | undefined;
            if (layout) return DecorationSet.create(tr.doc, [...layout.spacers.map(spacerDecoration), ...layout.shifts.map(shiftDecoration)]);
            return set.map(tr.mapping, tr.doc);
          },
        },
        props: {
          decorations: (state) => paginationKey.getState(state),
        },
        view: (view) => new Paginator(view, options),
      }),
    ];
  },
});

function spacerDecoration({ pos, height }: Spacer): Decoration {
  return Decoration.widget(
    pos,
    () => {
      const element = document.createElement("div");
      element.className = "page-spacer";
      element.style.height = `${height}px`;
      element.setAttribute("aria-hidden", "true");
      element.contentEditable = "false";
      return element;
    },
    { side: -1, key: `page-spacer-${height}`, ignoreSelection: true },
  );
}

function shiftDecoration({ from, to, style }: Shift): Decoration {
  return Decoration.node(from, to, { style }, { shift: style });
}

/** The spacers and column shifts laid out last time, by position. */
function currentLayout(state: EditorState): { spacers: Map<number, number>; shifts: Map<number, string> } {
  const spacers = new Map<number, number>();
  const shifts = new Map<number, string>();
  for (const decoration of paginationKey.getState(state)?.find() ?? []) {
    const spec = (decoration as unknown as { spec: { key?: string; shift?: string } }).spec;
    if (spec.shift !== undefined) shifts.set(decoration.from, spec.shift);
    else spacers.set(decoration.from, Number((spec.key ?? "").replace("page-spacer-", "")) || 0);
  }
  return { spacers, shifts };
}

// After a unit: the next one starts a new page -- any, or an even or odd one (a
// section break to an even or odd page, DOCX-015) -- or not.
export type Break = false | "any" | "even" | "odd";
type Unit = { pos: number; dom: HTMLElement; pageBreak: Break; section: boolean };

export function breakAfter(node: ProseMirrorNode): Break {
  if (node.type.name === "pageBreak") return "any";
  if (node.type.name !== "sectionBreak") return false;
  const start = (node.attrs.section as { start?: string } | null)?.start ?? "nextPage";
  return start === "continuous" ? false : start === "evenPage" ? "even" : start === "oddPage" ? "odd" : "any";
}

type SectionAttrs = Parameters<typeof sectionPage>[0] & { pageNumberStart?: number | null };

/** Each section's settings, in order: a section break holds the one it ends; the last is the document's (null). */
function sectionsIn(doc: ProseMirrorNode): (SectionAttrs | null)[] {
  const sections: (SectionAttrs | null)[] = [];
  doc.forEach((node) => {
    if (node.type.name === "sectionBreak") sections.push((node.attrs.section as SectionAttrs | null) ?? null);
  });
  return [...sections, null];
}

/** The blocks of each section whose text column isn't the document's, moved to its own. */
function sectionShifts(doc: ProseMirrorNode, boxes: PageBox[], base: PageBox): Shift[] {
  const shifts: Shift[] = [];
  let section = 0;
  doc.forEach((node, offset) => {
    const { left, right } = columnShift(boxes[Math.min(section, boxes.length - 1)], base);
    if (Math.abs(left) >= 0.5 || Math.abs(right) >= 0.5) {
      // A table's own margins are on the table inside Tiptap's wrapper, which the decoration moves.
      const style = node.type.name === "table" ? null : (node.attrs.style as string | null | undefined);
      shifts.push({
        from: offset,
        to: offset + node.nodeSize,
        style: `margin-left:${shiftedMargin(style, "left", left)};margin-right:${shiftedMargin(style, "right", right)}`,
      });
    }
    if (node.type.name === "sectionBreak") section += 1;
  });
  return shifts;
}

/** What gets laid out: top-level blocks, and each item of a top-level list. */
function layoutUnits(view: EditorView): Unit[] {
  const units: Unit[] = [];
  for (const block of blockDoms(view)) {
    const { node, pos: offset, dom } = block;
    if (LIST_TYPES.has(node.type.name)) {
      for (const item of block.children()) {
        if (item.dom instanceof HTMLElement) units.push({ pos: item.pos, dom: item.dom, pageBreak: false, section: false });
      }
      continue;
    }
    if (dom instanceof HTMLElement) units.push({ pos: offset, dom, pageBreak: breakAfter(node), section: node.type.name === "sectionBreak" });
  }
  return units;
}

/** The pages, made as the layout reaches them: a new one is the section's of the block that needs it. */
class Pages {
  readonly slots: PageSlot[] = [];

  constructor(
    private readonly boxes: PageBox[],
    private readonly gap: number,
  ) {}

  /** Makes sure page `index` exists; the pages it adds are `section`'s. */
  ensure(index: number, section: number) {
    while (this.slots.length <= index) {
      const previous = this.slots.at(-1);
      const top = previous ? previous.top + previous.box.height + this.gap : 0;
      this.slots.push({ top, section, box: this.boxes[Math.min(section, this.boxes.length - 1)] });
    }
  }

  /** The page `y` is on (its box and the gap after it), made if need be as `section`'s. */
  at(y: number, section: number): number {
    this.ensure(0, section);
    for (let last = this.slots.at(-1)!; y >= last.top + last.box.height + this.gap; last = this.slots.at(-1)!) {
      this.ensure(this.slots.length, section);
    }
    let low = 0;
    let high = this.slots.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (this.slots[middle].top <= y) low = middle;
      else high = middle - 1;
    }
    return low;
  }

  contentTop(page: number): number {
    return this.slots[page].top + this.slots[page].box.marginTop;
  }

  contentBottom(page: number): number {
    const slot = this.slots[page];
    return slot.top + slot.box.height - slot.box.marginBottom;
  }

  contentHeight(page: number): number {
    return this.contentBottom(page) - this.contentTop(page);
  }
}

// A timer rather than requestAnimationFrame: animation frames don't run while the
// tab is hidden, and a document opened in a background tab must still be laid out.
const LAYOUT_DELAY_MS = 30;

class Paginator {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly observer: ResizeObserver;
  private reportedPages = "";

  constructor(
    private readonly view: EditorView,
    private readonly options: PaginationOptions,
  ) {
    this.observer = new ResizeObserver(() => this.schedule());
    this.observer.observe(view.dom);
    // Pictures change height when they finish loading.
    view.dom.addEventListener("load", this.schedule, true);
    this.schedule();
  }

  // Any transaction (typing, a REPAGINATE request) gets a fresh layout; the timer
  // coalesces them, and a layout that changes nothing dispatches nothing.
  update(view: EditorView, previous: EditorState) {
    if (view.state !== previous) this.scheduleIn(layoutDelay(view.state, LAYOUT_DELAY_MS));
  }

  destroy() {
    clearTimeout(this.timer);
    this.observer.disconnect();
    this.view.dom.removeEventListener("load", this.schedule, true);
  }

  readonly schedule = () => this.scheduleIn(LAYOUT_DELAY_MS);

  private scheduleIn(delay: number) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.layout(), delay);
  }

  private layout() {
    const geometry = geometryOf(this.view);
    if (!geometry || !this.view.dom.isConnected) return;
    const { base, gap, scale } = geometry;
    const doc = this.view.state.doc;
    const sections = sectionsIn(doc);
    const boxes = sections.map((section) => (section ? sectionPage(section, base) : base));
    const pages = new Pages(boxes, gap);
    const shifts = sectionShifts(doc, boxes, base);

    const { spacers: existing, shifts: existingShifts } = currentLayout(this.view.state);
    const rootTop = this.view.dom.getBoundingClientRect().top;
    const next: Spacer[] = [];
    let shift = 0; // how much every later block moves with the spacers decided so far
    let startNewPage: Break = false;
    let bottom = 0;
    // Where each section's pages begin and the numbers they show (DOCX-015): a
    // section starts at its restart or runs on from the page before, and an even or
    // odd start goes by the number its first page shows, as Word's does.
    const restarts = [...sections.slice(0, -1).map((section) => section?.pageNumberStart ?? null), lastSectionRestart(this.view)];
    const numbering = [{ page: 0, number: restarts[0] ?? 1 }];
    const numberOf = (page: number) => {
      const start = [...numbering].reverse().find((entry) => entry.page <= page) ?? numbering[0];
      return start.number + page - start.page;
    };
    let sectionStart: Break | null = null; // after a section break: how the next section starts, until its first block is placed
    let breakPage = 0;
    let section = 0; // the section of the unit being placed

    for (const unit of layoutUnits(this.view)) {
      const rect = unit.dom.getBoundingClientRect();
      const oldSpacer = existing.get(unit.pos) ?? 0;
      const top = (rect.top - rootTop) / scale + shift - oldSpacer; // where it would sit with no spacer of its own
      const height = rect.height / scale;
      const page = pages.at(top, section);
      let spacer = 0;
      if (startNewPage) {
        let target = top > pages.contentTop(page) ? page + 1 : page;
        if (startNewPage === "even" || startNewPage === "odd") {
          const number = restarts[section] ?? numberOf(target - 1) + 1;
          if ((number % 2 === 0) !== (startNewPage === "even")) {
            pages.ensure(target, section - 1); // a blank page ends the section before
            target += 1;
          }
        }
        pages.ensure(target, section);
        spacer = pages.contentTop(target) - top;
      } else if (top < pages.contentTop(page)) {
        spacer = pages.contentTop(page) - top; // in the top margin or the gap between pages
      } else if (top >= pages.contentBottom(page) || (top + height > pages.contentBottom(page) && height <= pages.contentHeight(page))) {
        pages.ensure(page + 1, section);
        spacer = pages.contentTop(page + 1) - top;
      }
      spacer = Math.max(0, Math.round(spacer));
      if (spacer > 0) next.push({ pos: unit.pos, height: spacer });
      const placed = pages.at(top + spacer, section);
      if (sectionStart !== null) {
        // The section's own pages start with the one its first block is on -- a
        // continuous one's with the page after the one it begins on, which stays the
        // section before's, as in Word.
        const first = sectionStart === false ? breakPage + 1 : placed;
        numbering.push({ page: first, number: restarts[section] ?? numberOf(first - 1) + 1 });
        sectionStart = null;
      }
      shift += spacer - oldSpacer;
      bottom = Math.max(bottom, top + spacer + height);
      startNewPage = unit.pageBreak;
      if (unit.section) {
        sectionStart = unit.pageBreak;
        breakPage = placed;
        section += 1;
      }
    }

    const last = pages.at(Math.max(bottom - 1, 0), section);
    const count = startNewPage ? last + 2 : last + 1;
    pages.ensure(count - 1, section); // a break last: the page it starts, empty
    const laidOut = pages.slots.slice(0, count).map((slot) => ({ ...slot, top: Math.round(slot.top) }));
    const reported = JSON.stringify(laidOut);
    if (reported !== this.reportedPages) {
      this.reportedPages = reported;
      this.options.onPages(laidOut);
    }

    const changed =
      next.length !== existing.size ||
      next.some(({ pos, height }) => Math.abs((existing.get(pos) ?? -1000) - height) > SPACER_TOLERANCE_PX) ||
      shifts.length !== existingShifts.size ||
      shifts.some(({ from, style }) => existingShifts.get(from) !== style);
    if (changed) {
      this.view.dispatch(this.view.state.tr.setMeta(paginationKey, { spacers: next, shifts } satisfies Layout).setMeta("addToHistory", false));
    }
  }
}
