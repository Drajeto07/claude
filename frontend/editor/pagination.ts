import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, type EditorState } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";

/**
 * Real pages in the editor. The document is still one editable flow, but it is
 * laid out onto separate pages: a block that doesn't fit in what's left of a
 * page moves to the next one, and a page break starts a new page. It works by
 * measuring each block after every change and putting an invisible spacer in
 * front of the ones that have to move (spacers are decorations: they never
 * reach the saved document).
 *
 * A list moves item by item, so a long list continues on the next page. A single
 * block taller than a whole page (a very long table, say) can't be split and
 * runs past the page edge.
 */

export type PageGeometry = {
  /** Page height in CSS px. */
  pageHeight: number;
  /** Space between two pages, CSS px. */
  gap: number;
  marginTop: number;
  marginBottom: number;
  /** The CSS zoom the editor is shown at (measurements come back zoomed). */
  scale: number;
};

type Spacer = { pos: number; height: number };

const LIST_TYPES = new Set(["bulletList", "orderedList", "taskList"]);
const SPACER_TOLERANCE_PX = 1;

export const paginationKey = new PluginKey<DecorationSet>("pagination");

export type PaginationOptions = {
  onPageCount: (count: number) => void;
  /** Where each section after the first begins: the page (0-based) its own pages start on, in order (DOCX-015). */
  onSectionStarts?: (pages: number[]) => void;
};

/**
 * The page geometry, read from the element that lays the pages out: it carries
 * data-page-height, data-page-gap, data-margin-top, data-margin-bottom (CSS px)
 * and data-scale (the zoom), so the layout always matches what is on screen.
 */
function geometryOf(view: EditorView): PageGeometry | null {
  const container = view.dom.closest<HTMLElement>("[data-page-height]");
  if (!container) return null;
  const value = (name: string) => Number(container.dataset[name]);
  const geometry = {
    pageHeight: value("pageHeight"),
    gap: value("pageGap"),
    marginTop: value("marginTop"),
    marginBottom: value("marginBottom"),
    scale: value("scale") || 1,
  };
  return Object.values(geometry).every(Number.isFinite) && geometry.pageHeight > 0 ? geometry : null;
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
    return { onPageCount: () => undefined };
  },

  addProseMirrorPlugins() {
    const options = this.options;
    return [
      new Plugin<DecorationSet>({
        key: paginationKey,
        state: {
          init: () => DecorationSet.empty,
          apply(tr, set) {
            const spacers = tr.getMeta(paginationKey) as Spacer[] | undefined;
            if (spacers) return DecorationSet.create(tr.doc, spacers.map(spacerDecoration));
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

function currentSpacers(state: EditorState): Map<number, number> {
  const spacers = new Map<number, number>();
  for (const decoration of paginationKey.getState(state)?.find() ?? []) {
    const key = (decoration as unknown as { spec: { key?: string } }).spec.key ?? "";
    spacers.set(decoration.from, Number(key.replace("page-spacer-", "")) || 0);
  }
  return spacers;
}

// After a unit: the next one starts a new page -- any, or an even or odd one (a
// section break to an even or odd page, DOCX-015) -- or not.
export type Break = false | "any" | "even" | "odd";
type Unit = { pos: number; dom: HTMLElement; pageBreak: Break; section: boolean };
/** Each section's own page-number restart, in order: a section break holds the one
 * of the section it ends; the last section's is Document.lastSection's. */
function sectionRestarts(doc: ProseMirrorNode, last: number | null): (number | null)[] {
  const restarts: (number | null)[] = [];
  doc.forEach((node) => {
    if (node.type.name === "sectionBreak") restarts.push((node.attrs.section as { pageNumberStart?: number | null } | null)?.pageNumberStart ?? null);
  });
  return [...restarts, last];
}

export function breakAfter(node: ProseMirrorNode): Break {
  if (node.type.name === "pageBreak") return "any";
  if (node.type.name !== "sectionBreak") return false;
  const start = (node.attrs.section as { start?: string } | null)?.start ?? "nextPage";
  return start === "continuous" ? false : start === "evenPage" ? "even" : start === "oddPage" ? "odd" : "any";
}

/** What gets laid out: top-level blocks, and each item of a top-level list. */
function layoutUnits(view: EditorView): Unit[] {
  const units: Unit[] = [];
  view.state.doc.forEach((node: ProseMirrorNode, offset: number) => {
    if (LIST_TYPES.has(node.type.name)) {
      node.forEach((_item, itemOffset) => {
        const pos = offset + 1 + itemOffset;
        const dom = view.nodeDOM(pos);
        if (dom instanceof HTMLElement) units.push({ pos, dom, pageBreak: false, section: false });
      });
      return;
    }
    const dom = view.nodeDOM(offset);
    if (dom instanceof HTMLElement) units.push({ pos: offset, dom, pageBreak: breakAfter(node), section: node.type.name === "sectionBreak" });
  });
  return units;
}

// A timer rather than requestAnimationFrame: animation frames don't run while the
// tab is hidden, and a document opened in a background tab must still be laid out.
const LAYOUT_DELAY_MS = 30;

class Paginator {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly observer: ResizeObserver;
  private reportedStarts = "";

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
    if (view.state !== previous) this.schedule();
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
    const geometry = geometryOf(this.view);
    if (!geometry || !this.view.dom.isConnected) return;
    const { pageHeight, gap, marginTop, marginBottom, scale } = geometry;
    const stride = pageHeight + gap;
    const contentHeight = pageHeight - marginTop - marginBottom;
    const contentTop = (page: number) => page * stride + marginTop;
    const contentBottom = (page: number) => page * stride + pageHeight - marginBottom;
    const pageOf = (y: number) => Math.max(0, Math.floor(y / stride));

    const existing = currentSpacers(this.view.state);
    const rootTop = this.view.dom.getBoundingClientRect().top;
    const next: Spacer[] = [];
    let shift = 0; // how much every later block moves with the spacers decided so far
    let startNewPage: Break = false;
    let bottom = 0;
    // Where each section's own pages begin, and the numbers they show (DOCX-015): a
    // section starts at its restart or runs on from the page before, and an even or
    // odd start goes by the number its first page shows, as Word's does.
    const restarts = sectionRestarts(this.view.state.doc, lastSectionRestart(this.view));
    const numbering = [{ page: 0, number: restarts[0] ?? 1 }];
    const numberOf = (page: number) => {
      const start = [...numbering].reverse().find((entry) => entry.page <= page) ?? numbering[0];
      return start.number + page - start.page;
    };
    const sectionStarts: number[] = [];
    let sectionStart: Break | null = null; // after a section break: how the next section starts, until its first block is placed
    let breakPage = 0;

    for (const unit of layoutUnits(this.view)) {
      const rect = unit.dom.getBoundingClientRect();
      const oldSpacer = existing.get(unit.pos) ?? 0;
      const top = (rect.top - rootTop) / scale + shift - oldSpacer; // where it would sit with no spacer of its own
      const height = rect.height / scale;
      const page = pageOf(top);
      let spacer = 0;
      if (startNewPage) {
        let target = top > contentTop(page) ? page + 1 : page;
        if (startNewPage === "even" || startNewPage === "odd") {
          const number = restarts[sectionStarts.length + 1] ?? numberOf(target - 1) + 1;
          if ((number % 2 === 0) !== (startNewPage === "even")) target += 1; // a blank page ends the section before
        }
        spacer = contentTop(target) - top;
      } else if (top < contentTop(page)) {
        spacer = contentTop(page) - top; // in the top margin or the gap between pages
      } else if (top >= contentBottom(page) || (top + height > contentBottom(page) && height <= contentHeight)) {
        spacer = contentTop(page + 1) - top;
      }
      spacer = Math.max(0, Math.round(spacer));
      if (spacer > 0) next.push({ pos: unit.pos, height: spacer });
      if (sectionStart !== null) {
        // The section's own pages start with the one its first block is on -- a
        // continuous one's with the page after the one it begins on, which stays the
        // section before's, as in Word.
        const first = sectionStart === false ? breakPage + 1 : pageOf(top + spacer);
        numbering.push({ page: first, number: restarts[sectionStarts.length + 1] ?? numberOf(first - 1) + 1 });
        sectionStarts.push(first);
        sectionStart = null;
      }
      shift += spacer - oldSpacer;
      bottom = Math.max(bottom, top + spacer + height);
      startNewPage = unit.pageBreak;
      if (unit.section) {
        sectionStart = unit.pageBreak;
        breakPage = pageOf(top + spacer);
      }
    }
    if (sectionStart !== null) sectionStarts.push(sectionStart === false ? breakPage + 1 : pageOf(bottom) + 1); // a section break last

    const pages = startNewPage ? pageOf(bottom) + 2 : pageOf(Math.max(bottom - 1, 0)) + 1;
    this.options.onPageCount(Math.max(1, pages));
    const starts = sectionStarts.join(",");
    if (starts !== this.reportedStarts) {
      this.reportedStarts = starts;
      this.options.onSectionStarts?.(sectionStarts);
    }

    const changed =
      next.length !== existing.size ||
      next.some(({ pos, height }) => Math.abs((existing.get(pos) ?? -1000) - height) > SPACER_TOLERANCE_PX);
    if (changed) {
      this.view.dispatch(this.view.state.tr.setMeta(paginationKey, next).setMeta("addToHistory", false));
    }
  }
}
