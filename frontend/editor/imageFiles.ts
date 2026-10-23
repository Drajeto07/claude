import { Extension, type Editor } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";

/**
 * Pictures put into a document from the person's own device (S2-130): picked in a file dialog, pasted (Ctrl+V /
 * Cmd+V), or dropped onto the pages. Each is read here only far enough to refuse what can't be a picture -- by its
 * bytes, never its name or the type the browser says -- and goes in as an inline image (a data: URI), which the
 * next save sends to the server: that validates it again (security/files.py picture_problem), stores it among the
 * workspace's assets and points the element at it (services/image_assets.py). Nothing is fetched from elsewhere.
 */

/** The picture formats the server keeps (models/document.py WEB_IMAGE_TYPES). */
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"] as const;
/** What one picture may take: 3 MB. The save that carries it goes to the backend service on Vercel, whose
 * requests and answers are limited to 4.5 MB (Vercel Functions' limit, which applies to its container runtime too:
 * 413 FUNCTION_PAYLOAD_TOO_LARGE before the app sees it). The save is the change only (a PATCH), the picture as
 * base64 -- measured 1.334 times its bytes plus about 2 KB: 3 MB makes 4.2 MB. The server alone would take 20 MB. */
export const MAX_IMAGE_BYTES = 3 * 1024 * 1024;
/** As the server judges a picture's size (security/files.py). */
const MAX_PIXELS = 50_000_000;
const MAX_SIDE = 20_000;

export type ImageRejection = "notImage" | "tooLarge" | "unreadable";
export type ReadImage = { src: string } | { rejected: ImageRejection; name: string };

/** The picture format these bytes start with, or null: PNG, JPEG, GIF, WebP or BMP. */
export function sniffImageType(bytes: Uint8Array): (typeof IMAGE_TYPES)[number] | null {
  const starts = (...values: number[]) => values.every((value, index) => bytes[index] === value);
  const ascii = (from: number, text: string) => [...text].every((char, index) => bytes[from + index] === char.charCodeAt(0));
  if (starts(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return "image/png";
  if (starts(0xff, 0xd8, 0xff)) return "image/jpeg";
  if (ascii(0, "GIF87a") || ascii(0, "GIF89a")) return "image/gif";
  if (ascii(0, "RIFF") && ascii(8, "WEBP")) return "image/webp";
  if (ascii(0, "BM") && bytes.length > 26) return "image/bmp";
  return null;
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

/** The picture's size in pixels as the browser decodes it, or null if it can't. */
export type Decode = (src: string) => Promise<{ width: number; height: number } | null>;

export const decodeInBrowser: Decode = (src) =>
  new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image.naturalWidth > 0 && image.naturalHeight > 0 ? { width: image.naturalWidth, height: image.naturalHeight } : null);
    image.onerror = () => resolve(null);
    image.src = src;
  });

/** A file as a picture the document can take (a data: URI in its own format), or why not. */
export async function readImageFile(file: File, decode: Decode = decodeInBrowser): Promise<ReadImage> {
  const name = file.name;
  if (file.size > MAX_IMAGE_BYTES) return { rejected: "tooLarge", name };
  const bytes = new Uint8Array(await file.arrayBuffer());
  const type = sniffImageType(bytes);
  if (!type) return { rejected: "notImage", name };
  const src = `data:${type};base64,${base64(bytes)}`;
  const size = await decode(src);
  if (!size) return { rejected: "unreadable", name };
  if (size.width * size.height > MAX_PIXELS || Math.max(size.width, size.height) > MAX_SIDE) return { rejected: "tooLarge", name };
  return { src };
}

/**
 * Where pictures go for a position in the document: between top-level blocks, never inside one, so no paragraph is
 * split and no text moves. For the caret: after its block, or before it when the caret is at the block's very start.
 * For a drop (`pointer`): before the block when dropped on its first half, else after it. In an empty paragraph,
 * before it: it stays to type in.
 */
export function imageInsertPosition(doc: ProseMirrorNode, position: number, pointer = false): number {
  const at = Math.max(0, Math.min(position, doc.content.size));
  const $pos = doc.resolve(at);
  if ($pos.depth === 0) return at;
  const start = $pos.before(1);
  const end = $pos.after(1);
  const block = $pos.node(1);
  if (block.isTextblock && block.content.size === 0) return start;
  if (pointer) return at - start <= (end - start) / 2 ? start : end;
  return at <= start + 1 ? start : end;
}

/** The pictures put in at `position` (see imageInsertPosition), one after another, as one change to undo; returns
 * the position right after them (null if nothing went in). The caret stays where it was (moved with the change): a
 * picture left selected would be replaced by the next key typed. */
export function insertImages(editor: Editor, sources: string[], position: number, pointer = false): number | null {
  if (!sources.length || !editor.isEditable) return null;
  const at = imageInsertPosition(editor.state.doc, position, pointer);
  const before = editor.state.doc.content.size;
  const done = editor
    .chain()
    .focus()
    .insertContentAt(
      at,
      sources.map((src) => ({ type: "image", attrs: { src } })),
      { updateSelection: false },
    )
    .run();
  return done ? at + editor.state.doc.content.size - before : null;
}

function filesOf(data: DataTransfer | null): File[] {
  if (!data) return [];
  const fromItems = Array.from(data.items ?? [])
    .filter((item) => item.kind === "file")
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null);
  return fromItems.length ? fromItems : Array.from(data.files ?? []);
}

/** Whether pasted HTML holds no text -- only a picture, as a browser's "Copy image" or a copied Word picture gives. */
function onlyPictures(html: string): boolean {
  if (!html.trim()) return true;
  const body = new DOMParser().parseFromString(html, "text/html").body;
  return !(body.textContent ?? "").trim();
}

/** The files a paste brings that are meant as pictures: none when it brings text too -- text copied from Word
 * comes with a picture of itself, and must stay text. */
export function pastedFiles(data: DataTransfer | null): File[] {
  const files = filesOf(data);
  if (!files.length || !data) return [];
  if ((data.getData("text/plain") ?? "").trim()) return [];
  return onlyPictures(data.getData("text/html") ?? "") ? files : [];
}

/** The event the pages' element gets for files pasted or dropped onto them: `at` null for a paste (where the caret
 * is), else the document position under the pointer. The editor's owner (useEditorEngine) listens for it. */
export const IMAGE_FILES_EVENT = "smartdoc:image-files";
export type ImageFilesDetail = { files: File[]; at: number | null };

/** Pasting or dropping files hands them on (IMAGE_FILES_EVENT); everything else -- text, HTML, dragging text --
 * goes on as before. */
export const ImageFiles = Extension.create({
  name: "imageFiles",
  // Before the other paste handlers (PasteIntoEmptyBlock): they would take a paste of files for an empty one.
  priority: 1000,
  addProseMirrorPlugins() {
    const handOn = (dom: HTMLElement, detail: ImageFilesDetail) => dom.dispatchEvent(new CustomEvent<ImageFilesDetail>(IMAGE_FILES_EVENT, { detail }));
    return [
      new Plugin({
        key: new PluginKey("imageFiles"),
        props: {
          handlePaste(view, event) {
            const files = pastedFiles(event.clipboardData);
            if (!files.length) return false;
            event.preventDefault();
            handOn(view.dom, { files, at: null });
            return true;
          },
          handleDrop(view, event, _slice, moved) {
            if (moved) return false; // text dragged within the document
            const files = filesOf(event.dataTransfer);
            if (!files.length) return false;
            event.preventDefault();
            const at = view.posAtCoords({ left: event.clientX, top: event.clientY });
            handOn(view.dom, { files, at: at ? at.pos : null });
            return true;
          },
        },
      }),
    ];
  },
});
