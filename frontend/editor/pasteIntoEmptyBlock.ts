import { Extension } from "@tiptap/core";
import { Slice } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";

/**
 * Pasting into an empty paragraph puts the pasted blocks in its place, each with
 * its own attributes (a centred line stays centred). ProseMirror would pour the
 * first pasted paragraph's text into the empty one and drop its alignment
 * (tracker EDIT-008). Pasting into text that is already there is unchanged: the
 * first pasted line joins that paragraph, as in any editor.
 */
export const PasteIntoEmptyBlock = Extension.create({
  name: "pasteIntoEmptyBlock",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("pasteIntoEmptyBlock"),
        props: {
          handlePaste(view, _event, slice) {
            const { selection } = view.state;
            const target = selection.$from.parent;
            const first = slice.content.firstChild;
            if (!selection.empty || !target.isTextblock || target.content.size > 0 || slice.openStart === 0 || !first?.isTextblock) return false;
            // As ProseMirror's own paste does, with the slice's start closed: whole blocks, not text poured in.
            const closed = new Slice(slice.content, 0, slice.openEnd);
            view.dispatch(view.state.tr.replaceSelection(closed).scrollIntoView().setMeta("paste", true).setMeta("uiEvent", "paste"));
            return true;
          },
        },
      }),
    ];
  },
});
