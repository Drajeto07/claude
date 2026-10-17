import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import type { EditorView } from "@tiptap/pm/view";

/**
 * The DOM of each top-level block, and of each item of a top-level list, found in one walk
 * (tracker PERF-005). `view.nodeDOM(pos)` finds a block by walking the view's blocks from the
 * first one, so asking it for every block -- as the paginator and the float wrapping do on
 * every keystroke -- took time in the square of their number: most of a keystroke's time in a
 * 5,000-block document. This walks ProseMirror's own view descriptions (internal, so each is
 * checked against the document), and falls back to `nodeDOM` wherever they aren't as expected.
 */

type Desc = { node?: ProseMirrorNode | null; size: number; dom: Node; nodeDOM?: Node | null; children?: Desc[] };

export type BlockDom = {
  node: ProseMirrorNode;
  pos: number;
  dom: Node | null;
  /** The node's children, each with its DOM -- a list's items. */
  children: () => { node: ProseMirrorNode; pos: number; dom: Node | null }[];
};

function nodeDescs(descs: Desc[] | undefined, parent: ProseMirrorNode): Desc[] | null {
  if (!Array.isArray(descs)) return null;
  const found = descs.filter((desc) => desc.node); // widgets (page spacers) take no room
  if (found.length !== parent.childCount) return null;
  for (let index = 0; index < found.length; index += 1) if (found[index].node !== parent.child(index)) return null;
  return found;
}

function domOf(desc: Desc): Node {
  return desc.nodeDOM ?? desc.dom;
}

function childrenOf(view: EditorView, node: ProseMirrorNode, pos: number, desc: Desc | null) {
  const descs = desc ? nodeDescs(desc.children, node) : null;
  const children: { node: ProseMirrorNode; pos: number; dom: Node | null }[] = [];
  node.forEach((child, offset, index) => {
    const at = pos + 1 + offset;
    children.push({ node: child, pos: at, dom: descs ? domOf(descs[index]) : view.nodeDOM(at) });
  });
  return children;
}

export function blockDoms(view: EditorView): BlockDom[] {
  const { doc } = view.state;
  const descs = nodeDescs((view as unknown as { docView?: Desc }).docView?.children, doc);
  const blocks: BlockDom[] = [];
  doc.forEach((node, pos, index) => {
    const desc = descs ? descs[index] : null;
    blocks.push({ node, pos, dom: desc ? domOf(desc) : view.nodeDOM(pos), children: () => childrenOf(view, node, pos, desc) });
  });
  return blocks;
}
