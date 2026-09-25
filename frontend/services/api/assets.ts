import { API_BASE_URL } from "@/services/api/client";

const ASSET_URL_PREFIX = `${API_BASE_URL}/api/assets/`;

/** A stored image, fetched with the session cookie (same-site, so an <img> sends it). */
export function assetUrl(assetId: string): string {
  return `${ASSET_URL_PREFIX}${encodeURIComponent(assetId)}`;
}

/** The inverse of assetUrl, for turning an editor image node back into an asset reference. */
export function assetIdFromUrl(src: string): string | null {
  return src.startsWith(ASSET_URL_PREFIX) ? decodeURIComponent(src.slice(ASSET_URL_PREFIX.length)) : null;
}
