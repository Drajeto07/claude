import { sameContent } from "@/editor/tiptapToDocument";
import type { ContentPatch, ContentSaved, DirectStyle, Document, Element } from "@/types/document";

/**
 * Saving what changed instead of the whole document (корекции.docx §38, PERF-003).
 * A save sends the top-level elements changed, added and removed since the version
 * the editor last got from the server, and gets back how the stored document now
 * differs from it -- in a long document, one paragraph each way instead of all of
 * it. The threshold: when an existing block moved (a patch can't say that) or more
 * than WHOLE_SAVE_SHARE of the blocks changed, the whole document goes, as before.
 */
export const WHOLE_SAVE_SHARE = 0.5;
// A short document's patch is short anyway: below this many changed blocks, no whole save.
const WHOLE_SAVE_MIN_BLOCKS = 20;

// A top-level element's order is its place in the list, which the patch says otherwise
// (sameContent takes a field that is undefined as absent).
const withoutOrder = (element: Element) => ({ ...element, order: undefined });

/**
 * The patch that makes the server's `saved` top-level elements the editor's
 * `elements` (reconcileWithIds), with the editor's direct styles; null when the
 * whole document should be sent instead.
 */
export function contentPatch(elements: Element[], saved: Element[], styles: DirectStyle[]): ContentPatch | null {
  const before = new Map(saved.map((element) => [element.id, element]));
  const present = new Set(elements.map((element) => element.id));
  const kept = elements.filter((element) => before.has(element.id)).map((element) => element.id);
  const stayed = saved.filter((element) => present.has(element.id)).map((element) => element.id);
  if (present.size !== elements.length || kept.some((id, index) => id !== stayed[index])) return null;

  const changed: Element[] = [];
  const added: ContentPatch["added"] = [];
  elements.forEach((element, index) => {
    const was = before.get(element.id);
    if (!was) added.push({ after: index ? elements[index - 1].id : null, element });
    else if (!sameContent(withoutOrder(element), withoutOrder(was))) changed.push(element);
  });
  if (changed.length + added.length > Math.max(WHOLE_SAVE_MIN_BLOCKS, elements.length * WHOLE_SAVE_SHARE)) return null;
  const removed = saved.filter((element) => !present.has(element.id)).map((element) => element.id);
  return { changed, added, removed, styles };
}

/**
 * The document after a patch was saved: `base`, the version the patch was made
 * from, with the answer's elements in place, in `order` -- the patch's, unless the
 * answer gives the server's -- and every other part the answer names. What the
 * server now holds (backend content_delta; tests/test_content_patch.py checks the
 * same steps against the stored document). Throws when the answer names an
 * element neither has, which can't happen unless the two have come apart.
 */
export function applyContentSaved(base: Document, order: string[], saved: ContentSaved): Document {
  const byId = new Map(base.elements.map((element) => [element.id, element]));
  for (const element of saved.changed) byId.set(element.id, element);
  const elements = (saved.order ?? order).map((id, index) => {
    const element = byId.get(id);
    if (!element) throw new Error(`The saved document has an element this editor doesn't know (${id}).`);
    return element.order === index ? element : { ...element, order: index };
  });
  return { ...base, ...(saved.fields as Partial<Document>), elements, revision: saved.revision };
}
