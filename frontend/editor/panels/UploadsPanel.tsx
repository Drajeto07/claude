"use client";

import { ImageOff } from "lucide-react";
import { useEffect, useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { insertImages } from "@/editor/imageFiles";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { formatBytes } from "@/lib/format";
import { ApiError, assetUrl, listPictures } from "@/services/api";
import type { PictureAsset } from "@/types/document";

type Status = "loading" | "ready" | "failed" | "more";

/** The pictures of a page appended to those shown, each once (a picture stored meanwhile can shift a page). */
function appended(shown: PictureAsset[], page: PictureAsset[]): PictureAsset[] {
  const seen = new Set(shown.map((picture) => picture.id));
  return [...shown, ...page.filter((picture) => !seen.has(picture.id))];
}

/**
 * The Uploads panel (S2-131a), in the left side panel of both editors: the pictures the workspace's documents already
 * hold, newest first, a page at a time. One click puts one in after the selected block (or at the end, as a picture
 * picked from the device goes) by its asset id -- it isn't stored again, and the save is the document's usual one;
 * the server takes only the workspace's own pictures. Nothing here uploads, removes or keeps a picture: a picture no
 * document shows any more goes with the daily sweep where one runs (S2-131b would keep them).
 */
export function UploadsPanel() {
  const { document, editor, selection, flush } = useDocumentEditor();
  const documentId = document.id;
  const { m } = useI18n();
  const t = m.edPanels.uploads;
  const imageErrors = m.edBars.imageErrors;
  const [pictures, setPictures] = useState<PictureAsset[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [attempt, setAttempt] = useState(0);
  const [unavailable, setUnavailable] = useState<ReadonlySet<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listPictures(documentId)
      .then((page) => {
        if (!active) return;
        setPictures(page.items);
        setNext(page.next);
        setStatus("ready");
      })
      .catch(() => active && setStatus("failed"));
    return () => {
      active = false;
    };
  }, [documentId, attempt]);

  function retry() {
    setStatus("loading");
    setAttempt((count) => count + 1);
  }

  async function showMore() {
    if (!next) return;
    setStatus("more");
    try {
      const page = await listPictures(documentId, next);
      setPictures((shown) => appended(shown, page.items));
      setNext(page.next);
      setStatus("ready");
    } catch {
      setStatus("failed");
    }
  }

  async function insert(picture: PictureAsset) {
    setNotice(null);
    setError(null);
    if (!editor || editor.isDestroyed) return;
    if (!editor.isEditable) {
      setError(imageErrors.readOnly);
      return;
    }
    const at = selection.selectedElementId ? editor.state.selection.from : editor.state.doc.content.size;
    if (insertImages(editor, [assetUrl(picture.id)], at) === null) {
      setError(t.insertFailed);
      return;
    }
    setNotice(t.inserted);
    try {
      await flush();
    } catch (err) {
      // Otherwise the save says why (the status bar), as for a picture from the device.
      if (err instanceof ApiError && err.status === 413) setError(imageErrors.notSaved);
    }
  }

  return (
    <div className="flex flex-col gap-3" data-testid="uploads-panel">
      <p className="text-xs text-muted">{t.intro}</p>
      {status === "loading" && (
        <p role="status" className="text-sm text-muted">
          {t.loading}
        </p>
      )}
      {status === "failed" && (
        <div role="alert" className="flex flex-col items-start gap-2 text-sm text-danger">
          {t.failed}
          <button type="button" onClick={retry} className="rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-muted">
            {t.retry}
          </button>
        </div>
      )}
      {status !== "loading" && status !== "failed" && pictures.length === 0 && <p className="text-sm text-muted">{t.empty}</p>}
      {pictures.length > 0 && (
        <ul className="grid grid-cols-3 gap-2" aria-label={m.editor2.panels.uploads}>
          {pictures.map((picture, index) => {
            const number = index + 1;
            const missing = unavailable.has(picture.id);
            const label = missing ? format(t.unavailable, { number }) : format(t.insert, { number, size: formatBytes(picture.sizeBytes) });
            return (
              <li key={picture.id}>
                <button
                  type="button"
                  data-asset-id={picture.id}
                  aria-label={label}
                  title={label}
                  disabled={missing}
                  onClick={() => void insert(picture)}
                  className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-md border border-line bg-surface-muted hover:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {missing ? (
                    <ImageOff className="h-5 w-5 text-muted" aria-hidden="true" />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element -- a stored picture, served with the session cookie
                    <img
                      src={assetUrl(picture.id)}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      // After the page's own requests (a save waits for none of these pictures).
                      fetchPriority="low"
                      draggable={false}
                      onError={() => setUnavailable((ids) => new Set(ids).add(picture.id))}
                      className="h-full w-full object-contain"
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {next && status !== "failed" && (
        <button
          type="button"
          onClick={() => void showMore()}
          disabled={status === "more"}
          className="self-start rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50"
        >
          {status === "more" ? t.loading : t.more}
        </button>
      )}
      <p role="status" aria-live="polite" className="text-xs text-muted">
        {notice}
      </p>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
