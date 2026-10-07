/**
 * Fields in a header or footer's text (tracker DOCX-020A; the server's
 * formatting/header_fields.py). {PAGE} and {NUMPAGES} are the page number and count; any other
 * field the header holds -- STYLEREF, DATE, a document property -- is kept as
 * {FIELD <instruction>|<last result>}, shown on the page as its last result and written back to
 * Word as the field.
 */

const FIELD = /\{FIELD [^|{}]+\|([^{}]*)\}/g;

/** The text as a page shows it: its page-number fields filled in, each other field its last result. */
export function fillPageFields(text: string, page: string, pages: number): string {
  return text.replace(FIELD, (_, result: string) => result).replaceAll("{PAGE}", page).replaceAll("{NUMPAGES}", String(pages));
}
