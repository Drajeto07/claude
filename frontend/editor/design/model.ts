/**
 * Free Design Mode's model (docs/SMARTDOC_2_0_EDITOR_ARCHITECTURE.md, E3): positioned items on a fixed-size
 * page, the selection, and every change as a pure action -- so selection, moving, resizing, rotating,
 * snapping, stacking and undo are tested without a browser, and toolbar, keyboard and properties panel all
 * go through the same actions. Units are millimetres in page coordinates (top-left origin); the canvas
 * scales them by zoom. Not wired to any screen yet.
 */

export type ItemKind = "text" | "image" | "shape" | "line";

export type DesignItem = {
  id: string;
  kind: ItemKind;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Degrees, clockwise, around the item's centre. */
  rotation: number;
  /** Stacking order on the page: higher is in front. */
  z: number;
  locked?: boolean;
};

export type DesignPage = { id: string; width: number; height: number; items: DesignItem[] };

export type Rect = { x: number; y: number; width: number; height: number };

/** A guide line shown while snapping: vertical at x, or horizontal at y. */
export type Guide = { axis: "x" | "y"; at: number };

export type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

export type DesignState = {
  page: DesignPage;
  selected: string[];
  guides: Guide[];
  past: DesignPage[];
  future: DesignPage[];
  /** The kind of the last recorded step: a run of the same kind (one drag) is one undo step. */
  lastStep: string | null;
};

export type DesignAction =
  | { type: "select"; id: string | null; additive?: boolean }
  | { type: "selectArea"; area: Rect; additive?: boolean }
  | { type: "move"; dx: number; dy: number; snap?: number; gesture?: string }
  | { type: "nudge"; dx: number; dy: number }
  | { type: "resize"; handle: Handle; dx: number; dy: number; keepAspect?: boolean; fromCenter?: boolean; gesture?: string }
  | { type: "rotate"; degrees: number; snapTo?: number; gesture?: string }
  | { type: "endGesture" }
  | { type: "add"; item: DesignItem }
  | { type: "remove" }
  | { type: "duplicate"; newIds: string[]; offset?: number }
  | { type: "arrange"; to: "front" | "back" | "forward" | "backward" }
  | { type: "undo" }
  | { type: "redo" };

/** The smallest an item may become, mm. */
export const MIN_SIZE = 1;
/** Bounded history (architecture §7). */
export const HISTORY_LIMIT = 200;

export function createState(page: DesignPage): DesignState {
  return { page, selected: [], guides: [], past: [], future: [], lastStep: null };
}

// ----------------------------------------------------------------------------------------------- geometry

export function boundsOf(items: Rect[]): Rect | null {
  if (items.length === 0) return null;
  const left = Math.min(...items.map((item) => item.x));
  const top = Math.min(...items.map((item) => item.y));
  const right = Math.max(...items.map((item) => item.x + item.width));
  const bottom = Math.max(...items.map((item) => item.y + item.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function intersects(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** Where a selection moved by (dx, dy) snaps: to the page's edges and centre and to the other items' edges
 * and centres, on each axis separately, when within `threshold` mm. Returns the corrected move and the
 * guides to draw. */
export function snapMove(moving: Rect, others: Rect[], page: { width: number; height: number }, dx: number, dy: number, threshold: number) {
  const target = { ...moving, x: moving.x + dx, y: moving.y + dy };
  const lines = (rect: Rect, axis: "x" | "y") =>
    axis === "x" ? [rect.x, rect.x + rect.width / 2, rect.x + rect.width] : [rect.y, rect.y + rect.height / 2, rect.y + rect.height];
  const candidates = (axis: "x" | "y") => [
    ...(axis === "x" ? [0, page.width / 2, page.width] : [0, page.height / 2, page.height]),
    ...others.flatMap((other) => lines(other, axis)),
  ];
  const guides: Guide[] = [];
  const correct = (axis: "x" | "y") => {
    let best: { shift: number; at: number } | null = null;
    for (const own of lines(target, axis)) {
      for (const line of candidates(axis)) {
        const shift = line - own;
        if (Math.abs(shift) <= threshold && (best === null || Math.abs(shift) < Math.abs(best.shift))) best = { shift, at: line };
      }
    }
    if (best) guides.push({ axis, at: best.at });
    return best?.shift ?? 0;
  };
  return { dx: dx + correct("x"), dy: dy + correct("y"), guides };
}

/** An item's rectangle after dragging one of its handles by (dx, dy) -- in the item's own (unrotated) frame.
 * `keepAspect` keeps its proportions; `fromCenter` grows it on both sides. Never smaller than MIN_SIZE. */
export function resizeRect(rect: Rect, handle: Handle, dx: number, dy: number, keepAspect = false, fromCenter = false): Rect {
  const horizontal = handle.includes("e") ? 1 : handle.includes("w") ? -1 : 0;
  const vertical = handle.includes("s") ? 1 : handle.includes("n") ? -1 : 0;
  const factor = fromCenter ? 2 : 1;
  let width = rect.width + horizontal * dx * factor;
  let height = rect.height + vertical * dy * factor;
  if (keepAspect && horizontal !== 0 && vertical !== 0) {
    const ratio = rect.width / rect.height;
    // The larger relative change wins, the other side follows.
    if (Math.abs(width / rect.width) > Math.abs(height / rect.height)) height = width / ratio;
    else width = height * ratio;
  } else if (keepAspect && horizontal !== 0) {
    height = width * (rect.height / rect.width);
  } else if (keepAspect && vertical !== 0) {
    width = height * (rect.width / rect.height);
  }
  width = Math.max(MIN_SIZE, width);
  height = Math.max(MIN_SIZE, height);
  const grownX = width - rect.width;
  const grownY = height - rect.height;
  const x = fromCenter ? rect.x - grownX / 2 : horizontal === -1 ? rect.x - grownX : keepAspect && horizontal === 0 ? rect.x - grownX / 2 : rect.x;
  const y = fromCenter ? rect.y - grownY / 2 : vertical === -1 ? rect.y - grownY : keepAspect && vertical === 0 ? rect.y - grownY / 2 : rect.y;
  return { x, y, width, height };
}

// ------------------------------------------------------------------------------------------------ reducer

const editable = (state: DesignState) => state.page.items.filter((item) => state.selected.includes(item.id) && !item.locked);

/** Records the page as it was before a change; a change of the same gesture as the last one is the same
 * step (a whole drag undoes at once). */
function record(state: DesignState, page: DesignPage, step: string | null): DesignState {
  if (step !== null && step === state.lastStep) return { ...state, page, future: [] };
  const past = [...state.past, state.page].slice(-HISTORY_LIMIT);
  return { ...state, page, past, future: [], lastStep: step };
}

function withItems(page: DesignPage, update: (item: DesignItem) => DesignItem | null): DesignPage {
  return { ...page, items: page.items.map(update).filter((item): item is DesignItem => item !== null) };
}

export function designReducer(state: DesignState, action: DesignAction): DesignState {
  switch (action.type) {
    case "select": {
      if (action.id === null) return { ...state, selected: [] };
      if (!action.additive) return { ...state, selected: [action.id] };
      const selected = state.selected.includes(action.id) ? state.selected.filter((id) => id !== action.id) : [...state.selected, action.id];
      return { ...state, selected };
    }
    case "selectArea": {
      const inside = state.page.items.filter((item) => intersects(item, action.area)).map((item) => item.id);
      return { ...state, selected: action.additive ? [...new Set([...state.selected, ...inside])] : inside };
    }
    case "move":
    case "nudge": {
      const moving = editable(state);
      const bounds = boundsOf(moving);
      if (!bounds) return state;
      let { dx, dy } = action;
      let guides: Guide[] = [];
      if (action.type === "move" && action.snap) {
        const others = state.page.items.filter((item) => !state.selected.includes(item.id));
        ({ dx, dy, guides } = snapMove(bounds, others, state.page, dx, dy, action.snap));
      }
      const ids = new Set(moving.map((item) => item.id));
      const page = withItems(state.page, (item) => (ids.has(item.id) ? { ...item, x: item.x + dx, y: item.y + dy } : item));
      return { ...record(state, page, action.type === "move" ? (action.gesture ?? null) : null), guides };
    }
    case "resize": {
      const [only] = editable(state);
      if (!only || state.selected.length !== 1) return state;
      const next = resizeRect(only, action.handle, action.dx, action.dy, action.keepAspect, action.fromCenter);
      const page = withItems(state.page, (item) => (item.id === only.id ? { ...item, ...next } : item));
      return record(state, page, action.gesture ?? null);
    }
    case "rotate": {
      const ids = new Set(editable(state).map((item) => item.id));
      if (ids.size === 0) return state;
      const turn = (rotation: number) => {
        let degrees = (((rotation + action.degrees) % 360) + 360) % 360;
        if (action.snapTo) degrees = (Math.round(degrees / action.snapTo) * action.snapTo) % 360;
        return degrees;
      };
      const page = withItems(state.page, (item) => (ids.has(item.id) ? { ...item, rotation: turn(item.rotation) } : item));
      return record(state, page, action.gesture ?? null);
    }
    case "endGesture":
      return { ...state, guides: [], lastStep: null };
    case "add": {
      const z = Math.max(0, ...state.page.items.map((item) => item.z)) + 1;
      const page = { ...state.page, items: [...state.page.items, { ...action.item, z }] };
      return { ...record(state, page, null), selected: [action.item.id] };
    }
    case "remove": {
      const ids = new Set(editable(state).map((item) => item.id));
      if (ids.size === 0) return state;
      const page = withItems(state.page, (item) => (ids.has(item.id) ? null : item));
      return { ...record(state, page, null), selected: state.selected.filter((id) => !ids.has(id)) };
    }
    case "duplicate": {
      const originals = state.page.items.filter((item) => state.selected.includes(item.id));
      if (originals.length === 0 || action.newIds.length < originals.length) return state;
      const offset = action.offset ?? 5;
      let z = Math.max(0, ...state.page.items.map((item) => item.z));
      const copies = originals.map((item, index) => ({ ...item, id: action.newIds[index], x: item.x + offset, y: item.y + offset, z: ++z, locked: false }));
      const page = { ...state.page, items: [...state.page.items, ...copies] };
      return { ...record(state, page, null), selected: copies.map((copy) => copy.id) };
    }
    case "arrange": {
      const ids = new Set(state.selected);
      if (ids.size === 0) return state;
      const order = [...state.page.items].sort((a, b) => a.z - b.z);
      let arranged: DesignItem[];
      if (action.to === "front") arranged = [...order.filter((item) => !ids.has(item.id)), ...order.filter((item) => ids.has(item.id))];
      else if (action.to === "back") arranged = [...order.filter((item) => ids.has(item.id)), ...order.filter((item) => !ids.has(item.id))];
      else {
        arranged = [...order];
        const step = action.to === "forward" ? 1 : -1;
        const indices = arranged.map((item, index) => (ids.has(item.id) ? index : -1)).filter((index) => index >= 0);
        for (const index of step === 1 ? indices.reverse() : indices) {
          const swap = index + step;
          if (swap < 0 || swap >= arranged.length || ids.has(arranged[swap].id)) continue;
          [arranged[index], arranged[swap]] = [arranged[swap], arranged[index]];
        }
      }
      const zOf = new Map(arranged.map((item, index) => [item.id, index + 1]));
      const page = withItems(state.page, (item) => ({ ...item, z: zOf.get(item.id)! }));
      return record(state, page, null);
    }
    case "undo": {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return { ...state, page: previous, past: state.past.slice(0, -1), future: [state.page, ...state.future], lastStep: null, guides: [] };
    }
    case "redo": {
      const [next, ...rest] = state.future;
      if (!next) return state;
      return { ...state, page: next, past: [...state.past, state.page], future: rest, lastStep: null, guides: [] };
    }
  }
}
