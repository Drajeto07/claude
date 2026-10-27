import type { Editor } from "@tiptap/react";

import { assetIdFromUrl } from "@/services/api/assets";
import type { Element } from "@/types/document";

/**
 * Pictures a save sent that the server didn't keep (S2-131a). A save may put a stored picture in by its id (the
 * Uploads panel); the server leaves out one that isn't a picture of the document's workspace -- another workspace's,
 * one that no longer exists -- and saves the rest. The answer is what was stored, so the editor takes those pictures
 * out too: what it shows, and "Saved", are then what the server holds, and the person is told why.
 */

/** The stored pictures `elements` show, at any depth. */
export function pictureAssetIds(elements: readonly Element[], found: Set<string> = new Set()): Set<string> {
  for (const element of elements) {
    if (element.image?.assetId) found.add(element.image.assetId);
    if (element.children) pictureAssetIds(element.children, found);
    for (const item of element.listItems ?? []) if (item.blocks) pictureAssetIds(item.blocks, found);
    for (const row of element.table?.rows ?? []) for (const cell of row.cells) if (cell.blocks) pictureAssetIds(cell.blocks, found);
  }
  return found;
}

/** The pictures `sent` shows that `saved` (the server's answer to that save) doesn't. */
export function picturesLeftOut(sent: readonly Element[], saved: readonly Element[]): Set<string> {
  const kept = pictureAssetIds(saved);
  return new Set([...pictureAssetIds(sent)].filter((id) => !kept.has(id)));
}

/** Takes the editor's pictures showing these stored pictures out, wherever they are, as one change marked with
 * `meta` and kept out of the undo history (it isn't the person's edit); returns how many went. */
export function removePictures(editor: Editor, ids: ReadonlySet<string>, meta: string): number {
  if (ids.size === 0 || editor.isDestroyed) return 0;
  const ranges: [number, number][] = [];
  editor.state.doc.descendants((node, position) => {
    if (node.type.name !== "image") return true;
    const id = assetIdFromUrl(String(node.attrs.src ?? ""));
    if (id && ids.has(id)) ranges.push([position, position + node.nodeSize]);
    return false;
  });
  if (ranges.length === 0) return 0;
  const { tr } = editor.state;
  for (const [from, to] of ranges.reverse()) tr.delete(from, to);
  editor.view.dispatch(tr.setMeta("addToHistory", false).setMeta(meta, true));
  return ranges.length;
}
