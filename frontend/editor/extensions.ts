import { FontFamily } from "@tiptap/extension-font-family";
import { Image } from "@tiptap/extension-image";
import { TableKit } from "@tiptap/extension-table";
import { TextAlign } from "@tiptap/extension-text-align";
import { TextStyle } from "@tiptap/extension-text-style";
import StarterKit from "@tiptap/starter-kit";

import { AppliedStyle } from "./appliedStyle";
import { Caption } from "./caption";
import { ConfidenceIndicator } from "./confidenceIndicator";
import { ElementId } from "./elementId";
import { FontSize } from "./fontSize";
import { PageBreak } from "./pageBreak";

export const editorExtensions = [
  StarterKit,
  TableKit,
  // Stored images load from /api/assets; allowBase64 still matters for pasted images
  // and legacy documents, which the backend moves into asset storage on save.
  Image.configure({ allowBase64: true }),
  PageBreak,
  Caption,
  ConfidenceIndicator,
  AppliedStyle,
  ElementId,
  TextStyle,
  FontFamily,
  FontSize,
  TextAlign.configure({ types: ["heading", "paragraph"] }),
];
