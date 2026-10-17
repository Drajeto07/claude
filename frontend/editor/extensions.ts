import { FontFamily } from "@tiptap/extension-font-family";
import { Image } from "@tiptap/extension-image";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { Subscript } from "@tiptap/extension-subscript";
import { Superscript } from "@tiptap/extension-superscript";
import { TableKit } from "@tiptap/extension-table";
import { TextAlign } from "@tiptap/extension-text-align";
import { BackgroundColor, Color, TextStyle } from "@tiptap/extension-text-style";
import StarterKit from "@tiptap/starter-kit";

import { AppliedStyle } from "./appliedStyle";
import { Caption } from "./caption";
import { CharacterFormatting } from "./characterFormatting";
import { ConfidenceIndicator } from "./confidenceIndicator";
import { ElementId } from "./elementId";
import { FontSize } from "./fontSize";
import { Footnote } from "./footnote";
import { HeadingNumberedAttribute } from "./headingNumbers";
import { HiddenText } from "./hiddenText";
import { safeHref } from "./linkPolicy";
import { ListLabels } from "./listLabels";
import { ListNumberingAttribute } from "./listNumbering";
import { PageBreak } from "./pageBreak";
import { PasteIntoEmptyBlock } from "./pasteIntoEmptyBlock";
import { PictureAttribute, PictureLook } from "./pictureLook";
import { TextBox } from "./textBox";
import { SectionBreak } from "./sectionBreak";
import { TableCellBackground } from "./tableCellBackground";
import { TableLook, TableLookAttributes } from "./tableLook";

export const editorExtensions = [
  // A link only to an address the document can keep (SEC-014): pasted, typed or read,
  // any other stays text -- as the backend keeps it.
  StarterKit.configure({ link: { isAllowedUri: (url) => safeHref(url) !== null } }),
  TableKit,
  TableCellBackground,
  // A Word table's geometry and look: kept on the table, drawn by a plugin (DOCX-017).
  TableLookAttributes,
  TableLook,
  // Stored images load from /api/v1/assets; allowBase64 still matters for pasted images
  // and legacy documents, which the backend moves into asset storage on save.
  Image.configure({ allowBase64: true }),
  // A Word picture's size, crop, turn, flips and placement: kept on it, drawn by a plugin (DOCX-018).
  PictureAttribute,
  PictureLook,
  TextBox,
  PageBreak,
  SectionBreak,
  Caption,
  Footnote,
  ConfidenceIndicator,
  AppliedStyle,
  ElementId,
  // A list's own numbering from Word: its levels' labels, bullets and indents (DOCX-016),
  // and each item's label on the pages, as Word and the exports number it.
  ListNumberingAttribute,
  ListLabels,
  // Whether a heading is numbered in a document whose headings Word numbers (DOCX-016A);
  // the numbers themselves are drawn by HeadingNumbers, which needs the document.
  HeadingNumberedAttribute,
  // Checklists: a real, clickable checkbox per item (ListItem.checked).
  TaskList,
  TaskItem.configure({ nested: true }),
  // Character formatting (the Document Model's textStyle mark): font, size, colour, highlight,
  // and a language of its own -- a span with only a lang attribute is one too (DOCX-013).
  TextStyle.extend({
    parseHTML() {
      return [...(this.parent?.() ?? []), { tag: "span[lang]", consuming: false, getAttrs: () => ({}) }];
    },
  }),
  FontFamily,
  FontSize,
  Color,
  BackgroundColor,
  Superscript,
  Subscript,
  // Word's hidden text: kept, shown only on request (DOCX-025).
  HiddenText,
  // Underline and strikethrough styles, capitals, spacing, raised and lowered text (DOCX-013).
  CharacterFormatting,
  TextAlign.configure({ types: ["heading", "paragraph"] }),
  PasteIntoEmptyBlock,
];
