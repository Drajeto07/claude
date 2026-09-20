"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import { useState, type CSSProperties } from "react";

import { FormattingPanel } from "@/components/FormattingPanel";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { editorExtensions } from "@/editor/extensions";
import type { Document } from "@/types/document";

const PAGE_DIMENSIONS_MM: Record<string, { width: number; height: number }> = {
  A4: { width: 210, height: 297 },
  Letter: { width: 216, height: 279 },
  Legal: { width: 216, height: 356 },
};

// Continuous-scroll single-page visual approximation only -- real multi-page
// pagination with per-page repeated header/footer is a later phase's "real
// page preview" work, not this one's.
function pageWidthMm(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  return orientation === "landscape" ? dimensions.height : dimensions.width;
}

export function DocumentEditor({ initialDocument }: { initialDocument: Document }) {
  const [doc, setDoc] = useState(initialDocument);
  const editor = useEditor({
    extensions: editorExtensions,
    content: documentToTiptapJSON(doc),
    immediatelyRender: false,
  });

  function handleFormatted(updated: Document) {
    setDoc(updated);
    editor?.commands.setContent(documentToTiptapJSON(updated));
  }

  const { settings } = doc;
  const pageWidth = `${pageWidthMm(settings.pageSize, settings.orientation)}mm`;
  const paperPadding: CSSProperties = {
    paddingTop: `${settings.marginTopCm}cm`,
    paddingBottom: `${settings.marginBottomCm}cm`,
    paddingLeft: `${settings.marginLeftCm}cm`,
    paddingRight: `${settings.marginRightCm}cm`,
  };

  return (
    <div className="px-6 py-10">
      <div className="mx-auto max-w-3xl">
        <p className="mb-6 text-sm text-zinc-500">
          Editable draft &mdash; edits stay in your browser only; there is no save yet in this phase.
        </p>
        <FormattingPanel document={doc} onFormatted={handleFormatted} />
      </div>

      <div className="mx-auto" style={{ maxWidth: pageWidth }}>
        {settings.header && (
          <p className="mb-2 border-b border-zinc-200 pb-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
            {settings.header}
          </p>
        )}
        <div
          className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
          style={paperPadding}
        >
          <EditorContent editor={editor} />
        </div>
        {(settings.footer || settings.showPageNumbers) && (
          <p className="mt-2 border-t border-zinc-200 pt-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
            {[settings.footer, settings.showPageNumbers ? "1" : null].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>

      <p className="mx-auto mt-3 max-w-3xl text-center text-xs text-zinc-400">
        Page settings shown here are a single-page approximation -- real multi-page pagination comes in a later phase.
      </p>
    </div>
  );
}
