import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editorExtensions } from "@/editor/extensions";
import { reconcileElements } from "@/editor/tiptapToDocument";
import { I18nProvider } from "@/i18n/I18nProvider";
import { assetUrl } from "@/services/api/assets";
import type { PictureAsset } from "@/types/document";

import { UploadsPanel } from "./UploadsPanel";

/**
 * The Uploads panel (S2-131a): the workspace's pictures, a page at a time, and one click putting one in by its id --
 * after the selected block, or at the end -- then the usual save.
 */

const api = vi.hoisted(() => ({ listPictures: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("next/navigation", () => ({ usePathname: () => "/documents/x", useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const state = vi.hoisted(() => ({ value: null as unknown }));
vi.mock("@/editor/EditorState", () => ({ useDocumentEditor: () => state.value }));

const editors: Editor[] = [];
let flush: ReturnType<typeof vi.fn>;

function picture(id: string, sizeBytes = 2048): PictureAsset {
  return { id, contentType: "image/png", sizeBytes, createdAt: "2026-10-27T10:00:00Z" };
}

function editorWith(html: string, selectedElementId: string | null = null) {
  const editor = new Editor({ extensions: editorExtensions, content: html });
  editors.push(editor);
  flush = vi.fn().mockResolvedValue(undefined);
  state.value = { editor, selection: { selectedElementId, selectedElement: null, alignment: null }, flush, document: { id: "doc-1" } };
  return editor;
}

function blocks(editor: Editor): string[] {
  const names: string[] = [];
  editor.state.doc.forEach((node) => names.push(node.type.name === "image" ? `image:${node.attrs.src}` : node.textContent));
  return names;
}

beforeEach(() => api.listPictures.mockReset());
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

describe("listing the workspace's pictures", () => {
  it("says it is loading, then that there are none yet", async () => {
    editorWith("<p>Text</p>");
    let answer!: (value: unknown) => void;
    api.listPictures.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));

    render(<UploadsPanel />);

    expect(screen.getByText("Loading your pictures…")).toBeTruthy();
    answer({ items: [], next: null });
    expect(await screen.findByText(/No pictures yet/)).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("shows each one from its stored address, lazily, as a button to insert it", async () => {
    editorWith("<p>Text</p>");
    api.listPictures.mockResolvedValueOnce({ items: [picture("a"), picture("b", 3 * 1024 * 1024)], next: null });

    const { container } = render(<UploadsPanel />);

    const first = await screen.findByRole("button", { name: "Insert picture 1 (2 KB)" });
    expect(screen.getByRole("button", { name: "Insert picture 2 (3 MB)" })).toBeTruthy();
    expect(first.getAttribute("data-asset-id")).toBe("a");
    const images = Array.from(container.querySelectorAll("img"));
    expect(images.map((img) => img.getAttribute("src"))).toEqual([assetUrl("a"), assetUrl("b")]);
    expect(images.every((img) => img.getAttribute("loading") === "lazy" && img.getAttribute("alt") === "")).toBe(true);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
    expect(api.listPictures).toHaveBeenCalledWith("doc-1"); // the edited document's workspace
  });

  it("asks for the next page only when asked, and shows each picture once", async () => {
    editorWith("<p>Text</p>");
    api.listPictures
      .mockResolvedValueOnce({ items: [picture("a"), picture("b")], next: "b" })
      .mockResolvedValueOnce({ items: [picture("b"), picture("c")], next: null });

    render(<UploadsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Show more" }));

    await screen.findByRole("button", { name: /Insert picture 3/ });
    expect(api.listPictures).toHaveBeenLastCalledWith("doc-1", "b");
    expect(screen.getAllByRole("button", { name: /Insert picture/ }).map((b) => b.getAttribute("data-asset-id"))).toEqual(["a", "b", "c"]);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("says when they couldn't be loaded, and tries again", async () => {
    editorWith("<p>Text</p>");
    api.listPictures.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ items: [picture("a")], next: null });

    render(<UploadsPanel />);
    expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load your pictures.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("button", { name: /Insert picture 1/ })).toBeTruthy();
    expect(api.listPictures).toHaveBeenCalledTimes(2);
  });

  it("marks a picture that can't be shown, and doesn't put it in", async () => {
    const editor = editorWith("<p>Text</p>");
    api.listPictures.mockResolvedValueOnce({ items: [picture("gone")], next: null });

    const { container } = render(<UploadsPanel />);
    await screen.findByRole("button", { name: /Insert picture 1/ });
    fireEvent.error(container.querySelector("img")!);

    const button = screen.getByRole("button", { name: "Picture 1 can't be shown" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(blocks(editor)).toEqual(["Text"]);
  });

  it("speaks Bulgarian", async () => {
    editorWith("<p>Text</p>");
    api.listPictures.mockResolvedValueOnce({ items: [picture("a")], next: "a" });

    render(
      <I18nProvider locale="bg">
        <UploadsPanel />
      </I18nProvider>,
    );

    expect(await screen.findByRole("button", { name: "Вмъкни изображение 1 (2 KB)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Покажи още" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Качени изображения" })).toBeTruthy();
  });
});

describe("putting one in", () => {
  it("goes after the selected block, by its id, as one change, then saves", async () => {
    const editor = editorWith("<p>First</p><p>Second</p>", "selected");
    editor.commands.setTextSelection(3); // in "First"
    api.listPictures.mockResolvedValueOnce({ items: [picture("asset-7")], next: null });

    render(<UploadsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Insert picture 1/ }));

    await waitFor(() => expect(flush).toHaveBeenCalledTimes(1));
    expect(blocks(editor)).toEqual(["First", `image:${assetUrl("asset-7")}`, "Second"]);
    expect(screen.getByText("Picture inserted.")).toBeTruthy();
    // Saved as a reference to the stored picture, not its bytes.
    const saved = reconcileElements((editor.getJSON().content ?? []) as Parameters<typeof reconcileElements>[0], []);
    const image = saved.find((element) => element.type === "image")!;
    expect(image.image).toMatchObject({ assetId: "asset-7", src: "" });
    // One step to undo.
    editor.commands.undo();
    expect(blocks(editor)).toEqual(["First", "Second"]);
    editor.commands.redo();
    expect(blocks(editor)).toEqual(["First", `image:${assetUrl("asset-7")}`, "Second"]);
  });

  it("goes at the end when nothing is selected", async () => {
    const editor = editorWith("<p>First</p><p>Second</p>");
    api.listPictures.mockResolvedValueOnce({ items: [picture("asset-7")], next: null });

    render(<UploadsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Insert picture 1/ }));

    await waitFor(() => expect(flush).toHaveBeenCalled());
    // A paragraph stays after a final picture, to type in (as for one from the device).
    expect(blocks(editor)).toEqual(["First", "Second", `image:${assetUrl("asset-7")}`, ""]);
  });

  it("doesn't while the document is being formatted", async () => {
    const editor = editorWith("<p>First</p>");
    editor.setEditable(false);
    api.listPictures.mockResolvedValueOnce({ items: [picture("asset-7")], next: null });

    render(<UploadsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Insert picture 1/ }));

    expect((await screen.findByRole("alert")).textContent).toBe("Pictures can't be added while the document is being formatted.");
    expect(blocks(editor)).toEqual(["First"]);
    expect(flush).not.toHaveBeenCalled();
  });
});
