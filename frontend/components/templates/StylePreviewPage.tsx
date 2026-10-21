"use client";

import { useEffect, useRef, useState } from "react";

import { cssToStyle } from "@/editor/cssStyle";
import { fillPageFields } from "@/editor/headerFields";
import { PX_PER_MM } from "@/editor/pageGeometry";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { StylePreview } from "@/types/document";

/** The sample is page 1 of 1. */
function fillSamplePage(text: string): string {
  return fillPageFields(text, "1", 1);
}

/**
 * One sample page rendered with an (unsaved) style system's resolved styles:
 * real page size, margins, header and footer, scaled to fit the column. The
 * styles come from the backend engine (POST /api/v1/templates/preview) and the
 * page uses the editor's base CSS, so this is how a document will look.
 */
export function StylePreviewPage({ preview, stale }: { preview: StylePreview; stale: boolean }) {
  const { m } = useI18n();
  const t = m.templateEditor.preview;
  const sample = m.templateSamples.page; // sample words in the interface's language; header and footer are the template's own
  const frameRef = useRef<HTMLDivElement>(null);
  const [frameWidth, setFrameWidth] = useState(0);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new ResizeObserver(([entry]) => setFrameWidth(entry.contentRect.width));
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  const { resolvedStyles: styles, settings } = preview;
  const widthPx = settings.pageWidthMm * PX_PER_MM;
  const heightPx = settings.pageHeightMm * PX_PER_MM;
  const zoom = frameWidth > 0 ? Math.min(1, frameWidth / widthPx) : 0.5;
  const s = (target: string) => cssToStyle(styles[target]);

  return (
    <div ref={frameRef} className="w-full">
      <p className="mb-2 text-xs text-muted">
        {settings.pageSize} · {settings.orientation === "landscape" ? t.landscape : t.portrait} ·{" "}
        {format(t.margins, { values: [settings.marginTopCm, settings.marginRightCm, settings.marginBottomCm, settings.marginLeftCm].join(" / ") })}
        {stale && <span className="ml-2 text-accent">{t.updating}</span>}
      </p>
      <div
        aria-label={t.label}
        role="img"
        // Paper: white in both themes, as the page will print.
        className={`paper relative overflow-hidden rounded-lg border border-line bg-white shadow-card transition-opacity ${stale ? "opacity-70" : ""}`}
        style={{ zoom, width: widthPx, height: heightPx }}
      >
        {settings.header && (
          <div className="absolute inset-x-0 text-center text-xs text-slate-500" style={{ top: `${settings.marginTopCm / 2}cm` }}>
            {fillSamplePage(settings.header)}
          </div>
        )}
        <div
          className="ProseMirror"
          style={{
            paddingTop: `${settings.marginTopCm}cm`,
            paddingRight: `${settings.marginRightCm}cm`,
            paddingBottom: `${settings.marginBottomCm}cm`,
            paddingLeft: `${settings.marginLeftCm}cm`,
          }}
        >
          <h1 style={s("Heading 1")}>{sample.heading}</h1>
          <p style={s("Paragraph")}>{sample.paragraph}</p>
          <p style={s("Paragraph")}>{sample.second}</p>
          <h2 style={s("Heading 2")}>{sample.subheading}</h2>
          <ul style={s("List")}>
            {sample.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <blockquote style={s("Quote")}>{sample.quote}</blockquote>
          <h3 style={s("Heading 3")}>{sample.results}</h3>
          <table style={s("Table")}>
            <tbody>
              <tr>
                <th>{sample.measure}</th>
                <th>{sample.value}</th>
              </tr>
              <tr>
                <td>{sample.pages}</td>
                <td>42</td>
              </tr>
            </tbody>
          </table>
          <p data-caption="true" style={s("Caption")}>
            {sample.caption}
          </p>
          <pre style={s("CodeBlock")}>
            <code>{sample.code}</code>
          </pre>
        </div>
        {(settings.footer || settings.showPageNumbers) && (
          <div
            className="absolute inset-x-0 flex justify-center gap-4 text-xs text-slate-500"
            style={{ bottom: `${settings.marginBottomCm / 2}cm` }}
          >
            {settings.footer && <span>{fillSamplePage(settings.footer)}</span>}
            {settings.showPageNumbers && <span>{t.page}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
