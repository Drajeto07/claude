"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { ChangeHighlight, type ChangeKind } from "@/editor/changeHighlight";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { editorExtensions } from "@/editor/extensions";
import { PX_PER_MM } from "@/editor/pageGeometry";
import type { Document } from "@/types/document";

/**
 * A document shown read-only, as the editor draws it (the same extensions and
 * resolved styles, on a page of its width and margins, scaled to the column),
 * with the blocks in `changes` marked. Not paginated: one long page.
 */
export function DocumentPreview({ document, changes }: { document: Document; changes: Record<string, ChangeKind> }) {
  const extensions = useMemo(() => [...editorExtensions, ChangeHighlight.configure({ changes })], [changes]);
  const editor = useEditor({ extensions, content: documentToTiptapJSON(document), editable: false, immediatelyRender: false }, [document, extensions]);

  const frameRef = useRef<HTMLDivElement>(null);
  const [frameWidth, setFrameWidth] = useState(0);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const measure = () => setFrameWidth(frame.clientWidth);
    const observer = new ResizeObserver(measure);
    observer.observe(frame);
    // The observer's first call waits for a rendered frame, which a background tab never gets.
    const initial = setTimeout(measure, 0);
    return () => {
      observer.disconnect();
      clearTimeout(initial);
    };
  }, []);

  const { settings } = document;
  const pageWidthPx = settings.pageWidthMm * PX_PER_MM;
  const zoom = frameWidth > 0 ? Math.min(1, frameWidth / pageWidthPx) : 0.5;
  const pageStyle = {
    width: `${settings.pageWidthMm}mm`,
    minHeight: `${settings.pageHeightMm}mm`,
    zoom,
    "--page-margin-top": `${settings.marginTopCm}cm`,
    "--page-margin-right": `${settings.marginRightCm}cm`,
    "--page-margin-bottom": `${settings.marginBottomCm}cm`,
    "--page-margin-left": `${settings.marginLeftCm}cm`,
  } as CSSProperties;

  return (
    <div ref={frameRef} className="w-full">
      <div className="paged-editor document-preview border border-zinc-300 bg-white shadow-sm dark:border-zinc-700 dark:bg-zinc-900" style={pageStyle}>
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
