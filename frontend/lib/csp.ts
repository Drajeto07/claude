/**
 * The page Content-Security-Policy (SEC-020, корекции.docx §33), built per request
 * by proxy.ts with a fresh nonce. Scripts run only if they carry the nonce (or were
 * loaded by one that does: 'strict-dynamic'), so there is no 'unsafe-inline' in
 * script-src; Next.js puts the nonce on its own inline and bundled scripts when
 * the page is rendered for the request.
 */

/** A fresh, unguessable value for one response (16 random bytes, base64). */
export function generateNonce(): string {
  return btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16))));
}

export function buildContentSecurityPolicy({
  nonce,
  apiOrigin,
  isDev,
}: {
  nonce: string;
  /** Where the app's data and stored images come from (services/api/client.ts). */
  apiOrigin: string;
  isDev: boolean;
}): string {
  return [
    "default-src 'self'",
    // React needs 'unsafe-eval' in development only (stack reconstruction).
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // <style> elements need the nonce (Next's and Tiptap's, see NonceProvider).
    `style-src 'self' 'nonce-${nonce}'`,
    // Style *attributes* cannot carry a nonce. The browser also checks them when
    // HTML is parsed into an element, even a detached one, which is how the editor
    // reads pasted content and what ProseMirror's toDOM writes (text colour,
    // alignment, indents), so 'none' here would silently drop pasted formatting.
    // (React's own inline styles are set through the CSSOM, which is not
    // checked.) Style attributes cannot run script; this is the one place
    // 'unsafe-inline' remains.
    "style-src-attr 'unsafe-inline'",
    `img-src 'self' data: blob: ${apiOrigin}`,
    "font-src 'self' data:",
    // The dev server's hot reload talks over a WebSocket.
    `connect-src 'self' ${apiOrigin}${isDev ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(isDev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}
