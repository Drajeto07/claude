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
import { ConfidenceIndicator } from "./confidenceIndicator";
import { ElementId } from "./elementId";
import { FontSize } from "./fontSize";
import { PageBreak } from "./pageBreak";
import { TableCellBackground } from "./tableCellBackground";

export const editorExtensions = [
  StarterKit,
  TableKit,
  TableCellBackground,
  // Stored images load from /api/assets; allowBase64 still matters for pasted images
  // and legacy documents, which the backend moves into asset storage on save.
  Image.configure({ allowBase64: true }),
  PageBreak,
  Caption,
  ConfidenceIndicator,
  AppliedStyle,
  ElementId,
  // Checklists: a real, clickable checkbox per item (ListItem.checked).
  TaskList,
  TaskItem.configure({ nested: true }),
  // Character formatting (the Document Model's textStyle mark): font, size, colour, highlight.
  TextStyle,
  FontFamily,
  FontSize,
  Color,
  BackgroundColor,
  Superscript,
  Subscript,
  TextAlign.configure({ types: ["heading", "paragraph"] }),
];
