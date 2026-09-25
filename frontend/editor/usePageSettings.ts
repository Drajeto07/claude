"use client";

import type { Editor } from "@tiptap/react";
import { useEffect, useRef, useState } from "react";

import { PX_PER_MM } from "@/editor/pageGeometry";
import { REPAGINATE } from "@/editor/pagination";
import type { DocumentSettings } from "@/types/document";

// Space between two pages on screen, CSS px (like Word's page view).
export const PAGE_GAP_PX = 28;
export const CM_TO_PX = 10 * PX_PER_MM;
export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2;
const CANVAS_SIDE_PADDING_PX = 48; // matches the canvas's px-4/sm:px-6

/**
 * The document's page settings as the editor shows them: each page's size in
 * CSS pixels, the zoom (fitted to the column until the user picks one, never
 * enlarged), and the page count the pagination reports. Lays the pages out
 * again whenever any of it changes.
 */
export function usePageSettings(settings: DocumentSettings) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [pageCount, setPageCount] = useState(1);
  const [chosenZoom, setChosenZoom] = useState<number | null>(null);
  const [fitZoom, setFitZoom] = useState(1);
  const zoom = chosenZoom ?? fitZoom;

  const heightPx = settings.pageHeightMm * PX_PER_MM;
  const widthPx = settings.pageWidthMm * PX_PER_MM;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const fit = () => {
      const available = canvas.clientWidth - CANVAS_SIDE_PADDING_PX;
      setFitZoom(Math.max(MIN_ZOOM, Math.min(1, available / widthPx)));
    };
    const observer = new ResizeObserver(fit);
    observer.observe(canvas);
    // The observer's first call waits for a rendered frame, which a background tab never gets.
    const initial = setTimeout(fit, 0);
    return () => {
      observer.disconnect();
      clearTimeout(initial);
    };
  }, [widthPx]);

  function fitWidth() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setChosenZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, (canvas.clientWidth - CANVAS_SIDE_PADDING_PX) / widthPx)));
  }

  return { canvasRef, pageCount, setPageCount, zoom, setZoom: setChosenZoom, fitWidth, heightPx, widthPx, stridePx: heightPx + PAGE_GAP_PX };
}

export type PageSettings = ReturnType<typeof usePageSettings>;

/** New page size, margins or zoom: the pagination measures everything again. */
export function useRepaginate(editor: Editor | null, settings: DocumentSettings, page: PageSettings) {
  const { heightPx, zoom } = page;
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(REPAGINATE, true));
  }, [editor, heightPx, settings.marginTopCm, settings.marginBottomCm, zoom]);
}
