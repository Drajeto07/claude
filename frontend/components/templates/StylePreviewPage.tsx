"use client";

import { useEffect, useRef, useState } from "react";

import { cssToStyle } from "@/editor/cssStyle";
import { PX_PER_MM } from "@/editor/pageGeometry";
import type { StylePreview } from "@/types/document";

/** The sample is page 1 of 1. */
function fillSamplePage(text: string): string {
  return text.replaceAll("{PAGE}", "1").replaceAll("{NUMPAGES}", "1");
}

/**
 * One sample page rendered with an (unsaved) style system's resolved styles:
 * real page size, margins, header and footer, scaled to fit the column. The
 * styles come from the backend engine (POST /api/v1/templates/preview) and the
 * page uses the editor's base CSS, so this is how a document will look.
 */
export function StylePreviewPage({ preview, stale }: { preview: StylePreview; stale: boolean }) {
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
      <p className="mb-2 text-xs text-zinc-500 dark:text-zinc-400">
        {settings.pageSize} · {settings.orientation === "landscape" ? "landscape" : "portrait"} · margins {settings.marginTopCm} /{" "}
        {settings.marginRightCm} / {settings.marginBottomCm} / {settings.marginLeftCm} cm
        {stale && <span className="ml-2 text-accent">updating…</span>}
      </p>
      <div
        aria-label="Preview of a page in this template"
        role="img"
        className={`relative overflow-hidden rounded-md border border-zinc-200 bg-white text-zinc-900 shadow-sm transition-opacity dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50 ${stale ? "opacity-70" : ""}`}
        style={{ zoom, width: widthPx, height: heightPx }}
      >
        {settings.header && (
          <div className="absolute inset-x-0 text-center text-xs text-zinc-500" style={{ top: `${settings.marginTopCm / 2}cm` }}>
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
          <h1 style={s("Heading 1")}>1. Въведение</h1>
          <p style={s("Paragraph")}>
            Това е примерен абзац, оформен с текущите настройки на шаблона. Шрифтът, размерът, цветът, подравняването,
            междуредието и отстъпът на първия ред идват директно от стиловата система, както ще изглеждат в документа.
          </p>
          <p style={s("Paragraph")}>
            Втори абзац показва разстоянието между абзаците и как се подравнява по-дълъг текст, който се пренася на
            няколко реда в страницата.
          </p>
          <h2 style={s("Heading 2")}>1.1. Цели на работата</h2>
          <ul style={s("List")}>
            <li>Първа точка от списъка</li>
            <li>Втора точка от списъка</li>
            <li>Трета точка от списъка</li>
          </ul>
          <blockquote style={s("Quote")}>Цитат, който се откроява от основния текст.</blockquote>
          <h3 style={s("Heading 3")}>Резултати</h3>
          <table style={s("Table")}>
            <tbody>
              <tr>
                <th>Показател</th>
                <th>Стойност</th>
              </tr>
              <tr>
                <td>Брой страници</td>
                <td>42</td>
              </tr>
            </tbody>
          </table>
          <p data-caption="true" style={s("Caption")}>
            Таблица 1. Примерен надпис под таблица
          </p>
          <pre style={s("CodeBlock")}>
            <code>print(&quot;Здравей&quot;)</code>
          </pre>
        </div>
        {(settings.footer || settings.showPageNumbers) && (
          <div
            className="absolute inset-x-0 flex justify-center gap-4 text-xs text-zinc-500"
            style={{ bottom: `${settings.marginBottomCm / 2}cm` }}
          >
            {settings.footer && <span>{fillSamplePage(settings.footer)}</span>}
            {settings.showPageNumbers && <span>Page 1</span>}
          </div>
        )}
      </div>
    </div>
  );
}
