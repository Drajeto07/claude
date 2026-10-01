/**
 * Which addresses a link may have (SEC-014): the backend's app/security/links.py, rule for
 * rule, so the editor never makes a link the document can't keep -- tests/fixtures/
 * link-policy.json pins the two to the same answers. A Word file or a PDF opens its links
 * outside the app, so a link is an absolute address of a kind that opens a page, a mail,
 * a call or a chat: never javascript:, data:, vbscript: or file:, a UNC path, or a
 * relative address (a Word file resolves one against the folder it sits in).
 */

// Tiptap's own list, but cid: -- a part of an e-mail, nothing in a document.
export const SAFE_SCHEMES: readonly string[] = ["http", "https", "ftp", "ftps", "mailto", "tel", "callto", "sms", "xmpp"];
const MAX_HREF = 2048;
// Control codes the document drops (XML can't hold them) -- the ones that separate words
// become a space -- and what browsers remove inside an address before reading it.
const SEPARATORS = /[\u000b\u000c\u001c-\u001f]/g;
const DROPPED = /[\u0000-\u0008\u000e-\u001b\t\n\r\ufffe\uffff]|[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;
const SCHEME = /^([a-z][a-z0-9+.-]*):/i;

/** `value` as a link may keep it, or null. A bare "www." address gets https://. */
export function safeHref(value: string | null | undefined): string | null {
  if (!value) return null;
  let href = value.replace(SEPARATORS, " ").replace(DROPPED, "").trim();
  if (!href || href.length > MAX_HREF) return null;
  if (href.toLowerCase().startsWith("www.")) href = `https://${href}`;
  const scheme = SCHEME.exec(href)?.[1].toLowerCase();
  return scheme && SAFE_SCHEMES.includes(scheme) ? href : null;
}
