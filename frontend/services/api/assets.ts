import { API_BASE_URL, API_PREFIX } from "@/services/api/client";

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

/** The inverse of assetUrl, for turning an editor image node back into an asset reference. */
export function assetIdFromUrl(src: string): string | null {
  for (const prefix of [ASSET_URL_PREFIX, LEGACY_ASSET_URL_PREFIX]) {
    if (src.startsWith(prefix)) return decodeURIComponent(src.slice(prefix.length));
  }
  return null;
}
