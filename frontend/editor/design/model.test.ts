import { describe, expect, it } from "vitest";

import { createState, designReducer, HISTORY_LIMIT, MIN_SIZE, resizeRect, snapMove, type DesignAction, type DesignItem, type DesignState } from "./model";

const item = (id: string, x: number, y: number, width = 40, height = 20, extra: Partial<DesignItem> = {}): DesignItem => ({ id, kind: "shape", x, y, width, height, rotation: 0, z: 1, ...extra });

function page(...items: DesignItem[]): DesignState {
  return createState({ id: "p1", width: 210, height: 297, items: items.map((each, index) => ({ ...each, z: index + 1 })) });
}

const run = (state: DesignState, ...actions: DesignAction[]) => actions.reduce(designReducer, state);
const at = (state: DesignState, id: string) => state.page.items.find((each) => each.id === id)!;

describe("selection", () => {
  it("click selects one; shift-click adds and removes; click on nothing clears", () => {
    let state = page(item("a", 10, 10), item("b", 100, 10));
    state = run(state, { type: "select", id: "a" });
    expect(state.selected).toEqual(["a"]);
    state = run(state, { type: "select", id: "b", additive: true });
    expect(state.selected).toEqual(["a", "b"]);
    state = run(state, { type: "select", id: "a", additive: true });
    expect(state.selected).toEqual(["b"]);
    expect(run(state, { type: "select", id: null }).selected).toEqual([]);
  });

  it("a marquee selects every item it touches", () => {
    const state = run(page(item("a", 10, 10), item("b", 100, 10), item("c", 10, 200)), { type: "selectArea", area: { x: 0, y: 0, width: 120, height: 40 } });
    expect(state.selected).toEqual(["a", "b"]);
  });
});

describe("moving", () => {
  it("moves every selected item, but not a locked one", () => {
    const state = run(page(item("a", 10, 10), item("b", 100, 10, 40, 20, { locked: true })), { type: "select", id: "a" }, { type: "select", id: "b", additive: true }, { type: "move", dx: 5, dy: 7 });
    expect(at(state, "a")).toMatchObject({ x: 15, y: 17 });
    expect(at(state, "b")).toMatchObject({ x: 100, y: 10 });
  });

  it("snaps to the page centre and shows the guide", () => {
    // a: 40 wide; its centre at 30+20=50 moved by 52 lands at 102 -- 3 mm off the centre (105).
    const state = run(page(item("a", 30, 10)), { type: "select", id: "a" }, { type: "move", dx: 52, dy: 0, snap: 4 });
    expect(at(state, "a").x).toBe(85);
    expect(state.guides).toContainEqual({ axis: "x", at: 105 });
  });

  it("snaps to another item's edge; out of reach, it doesn't snap", () => {
    const others = [item("b", 100, 50)];
    expect(snapMove({ x: 10, y: 10, width: 20, height: 20 }, others, { width: 210, height: 297 }, 68, 0, 3).dx).toBe(70); // right edge 98 -> 100
    expect(snapMove({ x: 10, y: 10, width: 20, height: 20 }, others, { width: 210, height: 297 }, 60, 0, 3)).toMatchObject({ dx: 60, guides: [] });
  });

  it("a nudge moves by the arrow's step", () => {
    const state = run(page(item("a", 10, 10)), { type: "select", id: "a" }, { type: "nudge", dx: 0, dy: -1 });
    expect(at(state, "a").y).toBe(9);
  });
});

describe("resizing", () => {
  it("each handle moves its own edges", () => {
    const rect = { x: 10, y: 10, width: 40, height: 20 };
    expect(resizeRect(rect, "se", 10, 5)).toEqual({ x: 10, y: 10, width: 50, height: 25 });
    expect(resizeRect(rect, "nw", -10, -5)).toEqual({ x: 0, y: 5, width: 50, height: 25 });
    expect(resizeRect(rect, "e", 10, 99)).toEqual({ x: 10, y: 10, width: 50, height: 20 });
  });

  it("Shift keeps the proportions; Alt grows from the centre", () => {
    const rect = { x: 10, y: 10, width: 40, height: 20 };
    expect(resizeRect(rect, "se", 40, 0, true)).toEqual({ x: 10, y: 10, width: 80, height: 40 });
    expect(resizeRect(rect, "e", 10, 0, false, true)).toEqual({ x: 0, y: 10, width: 60, height: 20 });
  });

  it("never below the smallest size", () => {
    expect(resizeRect({ x: 0, y: 0, width: 10, height: 10 }, "se", -50, -50)).toMatchObject({ width: MIN_SIZE, height: MIN_SIZE });
  });

  it("only one item at a time", () => {
    const state = run(page(item("a", 10, 10), item("b", 100, 10)), { type: "select", id: "a" }, { type: "select", id: "b", additive: true }, { type: "resize", handle: "se", dx: 10, dy: 10 });
    expect(at(state, "a").width).toBe(40);
  });
});

describe("rotating, stacking, adding, duplicating, removing", () => {
  it("rotates around and snaps to 15° with Shift", () => {
    let state = run(page(item("a", 10, 10)), { type: "select", id: "a" }, { type: "rotate", degrees: -30 });
    expect(at(state, "a").rotation).toBe(330);
    state = run(state, { type: "rotate", degrees: 37, snapTo: 15 });
    expect(at(state, "a").rotation).toBe(0);
  });

  it("to front, to back, one step forward", () => {
    let state = page(item("a", 0, 0), item("b", 0, 0), item("c", 0, 0));
    state = run(state, { type: "select", id: "a" }, { type: "arrange", to: "front" });
    expect(at(state, "a").z).toBe(3);
    state = run(state, { type: "arrange", to: "back" });
    expect(at(state, "a").z).toBe(1);
    state = run(state, { type: "arrange", to: "forward" });
    expect([at(state, "b").z, at(state, "a").z, at(state, "c").z]).toEqual([1, 2, 3]);
  });

  it("a new item goes in front and is selected; a duplicate is offset, unlocked and selected", () => {
    let state = run(page(item("a", 10, 10, 40, 20, { locked: true })), { type: "add", item: item("n", 50, 50) });
    expect(at(state, "n").z).toBe(2);
    expect(state.selected).toEqual(["n"]);
    state = run(state, { type: "select", id: "a" }, { type: "duplicate", newIds: ["a2"] });
    expect(at(state, "a2")).toMatchObject({ x: 15, y: 15, locked: false, z: 3 });
    expect(state.selected).toEqual(["a2"]);
  });

  it("removing takes the selected items, not locked ones", () => {
    const state = run(page(item("a", 0, 0), item("b", 0, 0, 10, 10, { locked: true })), { type: "select", id: "a" }, { type: "select", id: "b", additive: true }, { type: "remove" });
    expect(state.page.items.map((each) => each.id)).toEqual(["b"]);
    expect(state.selected).toEqual(["b"]);
  });
});

describe("undo and redo", () => {
  it("a whole drag is one step; undo and redo walk it back and forth", () => {
    let state = run(page(item("a", 10, 10)), { type: "select", id: "a" });
    state = run(state, { type: "move", dx: 1, dy: 0, gesture: "drag-1" }, { type: "move", dx: 1, dy: 0, gesture: "drag-1" }, { type: "move", dx: 1, dy: 0, gesture: "drag-1" }, { type: "endGesture" });
    expect(at(state, "a").x).toBe(13);
    state = run(state, { type: "undo" });
    expect(at(state, "a").x).toBe(10);
    state = run(state, { type: "redo" });
    expect(at(state, "a").x).toBe(13);
  });

  it("each nudge is its own step; a new change clears what could be redone", () => {
    let state = run(page(item("a", 10, 10)), { type: "select", id: "a" }, { type: "nudge", dx: 1, dy: 0 }, { type: "nudge", dx: 1, dy: 0 }, { type: "undo" });
    expect(at(state, "a").x).toBe(11);
    state = run(state, { type: "nudge", dx: 0, dy: 1 });
    expect(state.future).toEqual([]);
  });

  it("history is bounded", () => {
    let state = run(page(item("a", 0, 0)), { type: "select", id: "a" });
    for (let step = 0; step < HISTORY_LIMIT + 20; step += 1) state = designReducer(state, { type: "nudge", dx: 1, dy: 0 });
    expect(state.past).toHaveLength(HISTORY_LIMIT);
  });

  it("nothing to undo: nothing changes", () => {
    const state = page(item("a", 0, 0));
    expect(designReducer(state, { type: "undo" })).toBe(state);
  });
});
