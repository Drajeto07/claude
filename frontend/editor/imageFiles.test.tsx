import { fireEvent, render, screen } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";

import { AddElementMenu } from "./AddElementMenu";
import { editorExtensions } from "./extensions";
import { IMAGE_FILES_EVENT, ImageFiles, imageInsertPosition, insertImages, MAX_IMAGE_BYTES, pastedFiles, readImageFile, sniffImageType, type ImageFilesDetail } from "./imageFiles";

/**
 * Pictures from the device (S2-130): read by their bytes, refused with a reason, put in between blocks, and handed
 * on from a paste or a drop -- while a paste of text, even text that comes with a picture of itself, stays text.
 */

vi.mock("next/navigation", () => ({ usePathname: () => "/documents/x", useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const PNG = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="), (c) => c.charCodeAt(0));
const JPEG = Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 16, 74, 70, 73, 70]);
const GIF = new TextEncoder().encode("GIF89a\u0001\u0000\u0001\u0000");
const WEBP = new TextEncoder().encode("RIFF\u0000\u0000\u0000\u0000WEBPVP8 ");
const BMP = Uint8Array.from([0x42, 0x4d, ...new Array(40).fill(0)]);
const decodes = async () => ({ width: 1, height: 1 });

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function editorWith(html: string) {
  const editor = new Editor({ extensions: [...editorExtensions, ImageFiles], content: html });
  editors.push(editor);
  return editor;
}

function file(bytes: Uint8Array, name: string, type: string) {
  return new File([bytes as BlobPart], name, { type });
}

describe("reading a picture by its bytes", () => {
  it.each([
    ["png", PNG, "image/png"],
    ["jpeg", JPEG, "image/jpeg"],
    ["gif", GIF, "image/gif"],
    ["webp", WEBP, "image/webp"],
    ["bmp", BMP, "image/bmp"],
  ])("knows %s", (_, bytes, type) => {
    expect(sniffImageType(bytes)).toBe(type);
  });

  it("knows no other format: an SVG, a PDF or text is no picture here", () => {
    for (const text of ["<svg xmlns='http://www.w3.org/2000/svg'/>", "%PDF-1.7", "just words"]) {
      expect(sniffImageType(new TextEncoder().encode(text))).toBeNull();
    }
  });

  it("takes the format from the bytes, not from the name or the type the browser gives", async () => {
    const read = await readImageFile(file(PNG, "photo.jpg", "image/jpeg"), decodes);
    expect(read).toEqual({ src: expect.stringMatching(/^data:image\/png;base64,iVBORw0KGgo/) });
  });

  it("refuses a file named and typed as a picture whose bytes aren't one", async () => {
    expect(await readImageFile(file(new TextEncoder().encode("not a picture"), "fake.png", "image/png"), decodes)).toEqual({ rejected: "notImage", name: "fake.png" });
  });

  it("takes up to 3 MB -- what one save can carry under the hosting's 4.5 MB request limit", () => {
    expect(MAX_IMAGE_BYTES).toBe(3 * 1024 * 1024);
    expect(Math.ceil(MAX_IMAGE_BYTES / 3) * 4 + 4096).toBeLessThan(4_500_000); // base64 and the rest of the change
  });

  it("refuses a picture over 3 MB before reading it", async () => {
    const big = new File([new Uint8Array(MAX_IMAGE_BYTES + 1)], "big.png", { type: "image/png" });
    const decode = vi.fn(decodes);
    expect(await readImageFile(big, decode)).toEqual({ rejected: "tooLarge", name: "big.png" });
    expect(decode).not.toHaveBeenCalled();
  });

  it("refuses one the browser can't decode, and one with too many pixels", async () => {
    expect(await readImageFile(file(PNG, "broken.png", "image/png"), async () => null)).toEqual({ rejected: "unreadable", name: "broken.png" });
    expect(await readImageFile(file(PNG, "huge.png", "image/png"), async () => ({ width: 30_000, height: 10 }))).toEqual({ rejected: "tooLarge", name: "huge.png" });
    expect(await readImageFile(file(PNG, "many.png", "image/png"), async () => ({ width: 8_000, height: 8_000 }))).toEqual({ rejected: "tooLarge", name: "many.png" });
  });
});

describe("where a picture goes", () => {
  const SRC = "data:image/png;base64,iVBORw0KGgo=";

  it("for the caret, after its paragraph -- before it only from its very start; never splitting it", () => {
    const editor = editorWith("<p>First paragraph</p><p>Second paragraph</p>");
    const doc = editor.state.doc;
    const first = doc.child(0);
    expect(imageInsertPosition(doc, 1)).toBe(0); // at the start: before it
    expect(imageInsertPosition(doc, 1 + 4)).toBe(first.nodeSize); // inside: after it
    expect(imageInsertPosition(doc, first.nodeSize - 1)).toBe(first.nodeSize); // at its end: after
  });

  it("for a drop, before or after the paragraph it lands on, by the half", () => {
    const editor = editorWith("<p>First paragraph</p><p>Second paragraph</p>");
    const doc = editor.state.doc;
    const first = doc.child(0);
    expect(imageInsertPosition(doc, 1 + 4, true)).toBe(0); // its first half: before
    expect(imageInsertPosition(doc, 1 + 12, true)).toBe(first.nodeSize); // its second half: after
  });

  it("before an empty paragraph, which stays to type in", () => {
    const editor = editorWith("<p>Text</p><p></p>");
    const empty = editor.state.doc.child(0).nodeSize;
    expect(imageInsertPosition(editor.state.doc, empty + 1)).toBe(empty);
  });

  it("after a table when the caret is in one of its cells", () => {
    const editor = editorWith("<table><tbody><tr><td><p>cell</p></td></tr></tbody></table><p>After</p>");
    const table = editor.state.doc.child(0);
    expect(imageInsertPosition(editor.state.doc, 6)).toBe(table.nodeSize);
  });

  it("is put in after the caret's paragraph with the text around it unchanged, as one change to undo", () => {
    const editor = editorWith("<p>Before the picture</p><p>After the picture</p>");
    editor.commands.setTextSelection(10);
    expect(insertImages(editor, [SRC, SRC], editor.state.selection.from)).toBe(editor.state.doc.child(0).nodeSize + 2);
    const types = editor.getJSON().content!.map((node) => node.type);
    expect(types).toEqual(["paragraph", "image", "image", "paragraph"]);
    expect(editor.getText()).toContain("Before the picture");
    expect(editor.state.doc.child(0).textContent).toBe("Before the picture");
    expect(editor.state.doc.child(3).textContent).toBe("After the picture");
    // The caret is still in the text, so typing goes on there -- it doesn't replace a picture.
    editor.commands.insertContent("X");
    expect(editor.state.doc.child(0).textContent).toBe("Before thXe picture");
    expect(editor.getJSON().content!.map((node) => node.type)).toEqual(["paragraph", "image", "image", "paragraph"]);
    editor.commands.undo();
    editor.commands.undo();
    expect(editor.getJSON().content!.map((node) => node.type)).toEqual(["paragraph", "paragraph"]);
  });

  it("isn't put in while the pages can't be edited", () => {
    const editor = editorWith("<p>Text</p>");
    editor.setEditable(false);
    expect(insertImages(editor, [SRC], 1)).toBeNull();
    expect(editor.getJSON().content!.map((node) => node.type)).toEqual(["paragraph"]);
  });
});

function clipboard({ files = [], text = "", html = "" }: { files?: File[]; text?: string; html?: string }): DataTransfer {
  return {
    items: files.map((one) => ({ kind: "file", type: one.type, getAsFile: () => one })),
    files,
    getData: (type: string) => (type === "text/plain" ? text : type === "text/html" ? html : ""),
  } as unknown as DataTransfer;
}

describe("what a paste brings", () => {
  const picture = file(PNG, "image.png", "image/png");

  it("a screenshot or a copied file: the picture", () => {
    expect(pastedFiles(clipboard({ files: [picture] }))).toEqual([picture]);
  });

  it("a browser's Copy image (HTML with only an img): the picture", () => {
    expect(pastedFiles(clipboard({ files: [picture], html: '<meta charset="utf-8"><img src="https://example.com/a.png">' }))).toEqual([picture]);
  });

  it("text copied from Word, which comes with a picture of itself: no files -- it stays text", () => {
    expect(pastedFiles(clipboard({ files: [picture], text: "Quarterly figures", html: "<p>Quarterly figures</p>" }))).toEqual([]);
  });

  it("plain text or HTML only: nothing", () => {
    expect(pastedFiles(clipboard({ text: "words" }))).toEqual([]);
    expect(pastedFiles(clipboard({ html: "<b>words</b>" }))).toEqual([]);
    expect(pastedFiles(null)).toEqual([]);
  });
});

describe("a paste or a drop in the editor", () => {
  function listen(editor: Editor) {
    const got: ImageFilesDetail[] = [];
    editor.view.dom.addEventListener(IMAGE_FILES_EVENT, (event) => got.push((event as CustomEvent<ImageFilesDetail>).detail));
    return got;
  }

  function paste(editor: Editor, data: DataTransfer) {
    const event = new Event("paste", { bubbles: true, cancelable: true }) as ClipboardEvent;
    Object.defineProperty(event, "clipboardData", { value: data });
    editor.view.dom.dispatchEvent(event);
    return event;
  }

  it("hands a pasted picture on, at the caret, and nothing goes into the text", () => {
    const editor = editorWith("<p>Text</p>");
    const got = listen(editor);
    const picture = file(PNG, "shot.png", "image/png");
    const event = paste(editor, clipboard({ files: [picture] }));
    expect(got).toEqual([{ files: [picture], at: null }]);
    expect(event.defaultPrevented).toBe(true);
    expect(editor.getText()).toBe("Text");
  });

  it("leaves a paste of text to the editor, as before", () => {
    const editor = editorWith("<p>Text</p>");
    const got = listen(editor);
    paste(editor, clipboard({ text: " more", html: "" }));
    expect(got).toEqual([]);
  });

  it("hands dropped files on with the position under the pointer; a drag of text isn't touched", () => {
    const editor = editorWith("<p>Text</p>");
    const got = listen(editor);
    const picture = file(PNG, "drop.png", "image/png");
    const plugin = editor.state.plugins.find((one) => (one as unknown as { key: string }).key.startsWith("imageFiles"))!;
    const drop = (moved: boolean) =>
      plugin.props.handleDrop!.call(plugin, editor.view, { dataTransfer: clipboard({ files: [picture] }), clientX: 0, clientY: 0, preventDefault() {} } as unknown as DragEvent, null as never, moved);
    vi.spyOn(editor.view, "posAtCoords").mockReturnValue({ pos: 3, inside: -1 });
    expect(drop(true)).toBe(false);
    expect(got).toEqual([]);
    expect(drop(false)).toBe(true);
    expect(got).toEqual([{ files: [picture], at: 3 }]);
  });
});

describe("the Add element menu", () => {
  it("offers a picture from the device, by mouse or keyboard, and hands the picked files on", () => {
    const onAddImage = vi.fn();
    render(
      <I18nProvider locale="en">
        <AddElementMenu onAdd={vi.fn()} onAddImage={onAddImage} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add element" }));
    const option = screen.getByRole("button", { name: "Image" });
    expect(option).toBeEnabled();
    const picker = screen.getByTestId("image-picker") as HTMLInputElement;
    expect(picker.accept).toBe("image/png,image/jpeg,image/gif,image/webp,image/bmp");
    const click = vi.spyOn(picker, "click");
    fireEvent.click(option);
    expect(click).toHaveBeenCalled();
    const picture = file(PNG, "logo.png", "image/png");
    fireEvent.change(picker, { target: { files: [picture] } });
    expect(onAddImage).toHaveBeenCalledWith([picture]);
  });

  it("says in Bulgarian what it takes", () => {
    render(
      <I18nProvider locale="bg">
        <AddElementMenu onAdd={vi.fn()} onAddImage={vi.fn()} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Добави елемент" }));
    expect(screen.getByRole("button", { name: "Изображение" })).toHaveAttribute("title", expect.stringContaining("до 3 MB"));
  });
});
