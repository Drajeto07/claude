import { API_BASE_URL, API_PREFIX } from "@/services/api/client";

// Always the browser's address: an image's src is rendered into the page.
const ASSET_URL_PREFIX = `${API_BASE_URL}${API_PREFIX}/assets/`;
// Images in an editor opened before the API moved under /api/v1.
const LEGACY_ASSET_URL_PREFIX = `${API_BASE_URL}/api/assets/`;

/** A stored image, fetched with the session cookie (same-site, so an <img> sends it). */
export function assetUrl(assetId: string): string {
  return `${ASSET_URL_PREFIX}${encodeURIComponent(assetId)}`;
}

/** The inverse of assetUrl, for turning an editor image node back into an asset reference. */
export function assetIdFromUrl(src: string): string | null {
  for (const prefix of [ASSET_URL_PREFIX, LEGACY_ASSET_URL_PREFIX]) {
    if (src.startsWith(prefix)) return decodeURIComponent(src.slice(prefix.length));
  }
  return null;
}
