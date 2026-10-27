import { API_BASE_URL, API_PREFIX, apiFetch, jsonOrThrow } from "@/services/api/client";
import type { PicturePage } from "@/types/document";

// Always the browser's address: an image's src is rendered into the page.
const ASSET_URL_PREFIX = `${API_BASE_URL}${API_PREFIX}/assets/`;
// Images in an editor opened before the API moved under /api/v1.
const LEGACY_ASSET_URL_PREFIX = `${API_BASE_URL}/api/assets/`;

/** A stored image, fetched with the session cookie (same-site, so an <img> sends it). */
export function assetUrl(assetId: string): string {
  return `${ASSET_URL_PREFIX}${encodeURIComponent(assetId)}`;
}

/**
 * A project's first-page thumbnail (SmartDoc 2.0). `version` (its last change) makes each version
 * its own URL: the browser keeps it for good, and the server draws it once per revision.
 */
export function thumbnailUrl(documentId: string, version: string): string {
  return `${API_BASE_URL}${API_PREFIX}/documents/${encodeURIComponent(documentId)}/thumbnail?v=${encodeURIComponent(version)}`;
}

/** How many pictures one page of the Uploads panel asks for (the API takes at most 48). Each is shown from the stored
 * picture itself (up to 3 MB; no small thumbnails before S2-131b), and a page fits the panel without scrolling, so
 * loading lazily saves nothing on it: 12 keeps a first look at most about 36 MB (measured 2026-10-27: 24 pictures of
 * 2.4 MB = 58 MB), the rest on "Show more". */
export const PICTURE_PAGE_SIZE = 12;

/**
 * The pictures of the workspace `documentId` is in (what a save of it accepts), newest first, a page at a time
 * (S2-131a): `before` is the previous page's `next`. Each is shown from assetUrl and put in a document again by its
 * id -- never stored twice.
 */
export async function listPictures(documentId: string, before: string | null = null, limit: number = PICTURE_PAGE_SIZE): Promise<PicturePage> {
  const query = new URLSearchParams({ documentId, limit: String(limit) });
  if (before) query.set("before", before);
  return jsonOrThrow(await apiFetch(`/assets?${query}`, { cache: "no-store" }), "Failed to load your pictures");
}

/** The inverse of assetUrl, for turning an editor image node back into an asset reference. */
export function assetIdFromUrl(src: string): string | null {
  for (const prefix of [ASSET_URL_PREFIX, LEGACY_ASSET_URL_PREFIX]) {
    if (src.startsWith(prefix)) return decodeURIComponent(src.slice(prefix.length));
  }
  return null;
}
