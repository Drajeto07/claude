import { Image } from "@tiptap/extension-image";
import { TableKit } from "@tiptap/extension-table";
import StarterKit from "@tiptap/starter-kit";

import { AppliedStyle } from "./appliedStyle";
import { ConfidenceIndicator } from "./confidenceIndicator";

export const editorExtensions = [
  StarterKit,
  TableKit,
  // Our DOCX parser embeds images as base64 data: URIs (never touches disk,
  // per spec Section 16) -- allowBase64 is required or those sources are stripped.
  Image.configure({ allowBase64: true }),
  ConfidenceIndicator,
  AppliedStyle,
];
