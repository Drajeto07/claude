import { FontFamily } from "@tiptap/extension-font-family";
import { Image } from "@tiptap/extension-image";
import { TableKit } from "@tiptap/extension-table";
import { TextAlign } from "@tiptap/extension-text-align";
import { TextStyle } from "@tiptap/extension-text-style";
import StarterKit from "@tiptap/starter-kit";

import { AppliedStyle } from "./appliedStyle";
import { ConfidenceIndicator } from "./confidenceIndicator";
import { ElementId } from "./elementId";
import { FontSize } from "./fontSize";
import { PageBreak } from "./pageBreak";

export const editorExtensions = [
  StarterKit,
  TableKit,
  // Our DOCX parser embeds images as base64 data: URIs (never touches disk,
  // per spec Section 16) -- allowBase64 is required or those sources are stripped.
  Image.configure({ allowBase64: true }),
  PageBreak,
  ConfidenceIndicator,
  AppliedStyle,
  ElementId,
  TextStyle,
  FontFamily,
  FontSize,
  TextAlign.configure({ types: ["heading", "paragraph"] }),
];
