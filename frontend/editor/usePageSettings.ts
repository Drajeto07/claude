"use client";

import type { Editor } from "@tiptap/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { PX_PER_MM } from "@/editor/pageGeometry";
import { REPAGINATE } from "@/editor/pagination";
import type { SectionSettings } from "@/editor/sectionHeaders";
import { basePage, type PageBox, type PageSlot } from "@/editor/sectionPages";
import type { DocumentSettings } from "@/types/document";

// Space between two pages on screen, CSS px (like Word's page view).
export const PAGE_GAP_PX = 28;
export const CM_TO_PX = 10 * PX_PER_MM;
export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2;
const CANVAS_SIDE_PADDING_PX = 48; // matches the canvas's px-4/sm:px-6

/**
 * The document's pages as the editor shows them: where each starts, its section and
 * its size and margins, as the pagination lays them out -- each section's own
 * (DOCX-015) -- and the zoom (fitted to the column until the user picks one, never
 * enlarged), which fits the widest page. `base` is the document's own page (the last
 * section's).
 */
export function usePageSettings(settings: DocumentSettings, lastSection?: SectionSettings | null) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [laidOut, setPages] = useState<PageSlot[] | null>(null);
  const [chosenZoom, setChosenZoom] = useState<number | null>(null);
  const [fitZoom, setFitZoom] = useState(1);
  const zoom = chosenZoom ?? fitZoom;

  // By value: the settings object is new after every save, the page seldom is.
  const baseKey = JSON.stringify(basePage(settings, lastSection));
  const base = useMemo(() => JSON.parse(baseKey) as PageBox, [baseKey]);
  const pages = useMemo(() => (laidOut?.length ? laidOut : [{ top: 0, section: 0, box: base }]), [laidOut, base]);
  const widest = Math.max(base.width, ...pages.map((slot) => slot.box.width));
  const last = pages[pages.length - 1];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const fit = () => {
      const available = canvas.clientWidth - CANVAS_SIDE_PADDING_PX;
      setFitZoom(Math.max(MIN_ZOOM, Math.min(1, available / widest)));
    };
    const observer = new ResizeObserver(fit);
    observer.observe(canvas);
    // The observer's first call waits for a rendered frame, which a background tab never gets.
    const initial = setTimeout(fit, 0);
    return () => {
      observer.disconnect();
      clearTimeout(initial);
    };
  }, [widest]);

  function fitWidth() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setChosenZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, (canvas.clientWidth - CANVAS_SIDE_PADDING_PX) / widest)));
  }

  return {
    canvasRef,
    pages,
    pageCount: pages.length,
    setPages,
    zoom,
    setZoom: setChosenZoom,
    fitWidth,
    base,
    /** The widest page's width, CSS px: the sheet's. */
    widest,
    /** From the first page's top to the last one's bottom, CSS px. */
    heightPx: last.top + last.box.height,
  };
}

export type PageSettings = ReturnType<typeof usePageSettings>;

/** New page size, margins or zoom: the pagination measures everything again. */
export function useRepaginate(editor: Editor | null, page: PageSettings) {
  const { base, zoom } = page;
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(REPAGINATE, true));
  }, [editor, base, zoom]);
}
