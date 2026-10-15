"use client";

import { useMemo, useSyncExternalStore } from "react";

export type PanelId = "structure" | "templates" | "instructions" | "translate" | "review" | "page" | "history" | "health" | "check" | "doctor";

type Saved = { panel: PanelId | null; properties: boolean | null; hidden: boolean };

const KEY = "smartdoc:editor2:layout";
const EMPTY: Saved = { panel: null, properties: null, hidden: false };
const listeners = new Set<() => void>();
// Kept in memory too, so the layout still works where storage is blocked (private windows).
let memory: string | null = null;

function snapshot(): string | null {
  try {
    return window.localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

function store(saved: Saved) {
  memory = JSON.stringify(saved);
  try {
    window.localStorage.setItem(KEY, memory);
  } catch {
    // Storage blocked: the memory copy serves this page.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function parse(raw: string | null): Saved {
  try {
    const saved = JSON.parse(raw ?? "null") as Partial<Saved> | null;
    return saved ? { ...EMPTY, ...saved } : EMPTY;
  } catch {
    return EMPTY;
  }
}

/**
 * Which side panel is open, whether the properties show, and whether every panel is hidden for the most room on
 * the page (E2: easy to hide and bring back -- one button, or Ctrl+\). Remembered in this browser only, read on
 * the client (the server renders the default, so hydration matches): a convenience, never anything a document
 * depends on.
 */
export function usePanelLayout() {
  const raw = useSyncExternalStore(subscribe, snapshot, () => null);
  const saved = useMemo(() => parse(raw), [raw]);
  const update = (change: Partial<Saved>) => store({ ...saved, ...change });
  return {
    panel: saved.hidden ? null : saved.panel,
    properties: saved.hidden ? false : saved.properties,
    hidden: saved.hidden,
    setPanel: (panel: PanelId | null) => update({ panel, hidden: false }),
    setProperties: (properties: boolean) => update({ properties, hidden: false }),
    togglePanels: () => update({ hidden: !saved.hidden }),
  };
}
