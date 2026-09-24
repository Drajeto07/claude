export type ElementType =
  | "heading"
  | "paragraph"
  | "list"
  | "table"
  | "image"
  | "quote"
  | "caption"
  | "footnote"
  | "code_block"
  | "page_break"
  | "other";

export type MarkType = "bold" | "italic" | "underline" | "strike" | "code" | "link";

export interface Mark {
  type: MarkType;
  href: string | null;
}

export interface InlineRun {
  text: string;
  marks: Mark[];
}

export interface ListItem {
  id: string;
  inline: InlineRun[];
  level: number;
  checked: boolean | null;
}

export interface TableCell {
  id: string;
  inline: InlineRun[];
  header: boolean;
  colspan: number;
  rowspan: number;
}

export interface TableRow {
  id: string;
  cells: TableCell[];
}

export interface TableContent {
  rows: TableRow[];
  hasHeaderRow: boolean;
  alignments: (string | null)[] | null;
}

export interface ImageContent {
  /** Empty when assetId is set; otherwise an external URL or a legacy data: URI. */
  src: string;
  assetId: string | null;
  alt: string | null;
  title: string | null;
}

export interface Element {
  id: string;
  type: ElementType;
  content: string;
  inline: InlineRun[] | null;
  listItems: ListItem[] | null;
  ordered: boolean;
  table: TableContent | null;
  image: ImageContent | null;
  language: string | null;
  parentId: string | null;
  order: number;
  level: number | null;
  confidence: number | null;
  styleRef: string | null;
  /** Preservation layer (spec §9/§11) -- opaque, never read/written by the
   * editor. Not yet populated by any parser; see backend models/document.py. */
  preservedAttributes: Record<string, unknown> | null;
}

export type FormattingProperty =
  | "fontFamily"
  | "fontSize"
  | "bold"
  | "italic"
  | "underline"
  | "color"
  | "alignment"
  | "lineSpacing"
  | "paragraphSpacing"
  | "firstLineIndent"
  | "imageWidth"
  | "imageAlignment"
  | "pageSize"
  | "orientation"
  | "marginTop"
  | "marginBottom"
  | "marginLeft"
  | "marginRight"
  | "header"
  | "footer"
  | "showPageNumbers";

export interface FormattingRule {
  id: string;
  target: string;
  property: FormattingProperty;
  value: string;
  unit: string | null;
  priority: number;
  source: string;
}

export interface DocumentMetadata {
  title: string;
  createdAt: string;
  updatedAt: string;
  sourceType: string;
  originalFilename: string | null;
}

export interface DocumentSettings {
  pageSize: string;
  orientation: string;
  marginTopCm: number;
  marginBottomCm: number;
  marginLeftCm: number;
  marginRightCm: number;
  header: string | null;
  footer: string | null;
  showPageNumbers: boolean;
}

export interface Section {
  id: string;
  title: string | null;
  order: number;
}

export interface Revision {
  id: string;
  createdAt: string;
  description: string;
}

export interface Document {
  id: string;
  schemaVersion: number;
  /** Concurrency token; sent back as If-Match on every change (services/api.ts). */
  revision: number;
  metadata: DocumentMetadata;
  documentType: string;
  templateId: string | null;
  settings: DocumentSettings;
  sections: Section[];
  elements: Element[];
  formattingRules: FormattingRule[];
  revisions: Revision[];
  resolvedStyles: Record<string, Record<string, string>>;
  /** Human-readable notes about something a parser detected but could not
   * fully preserve (spec §9 strategy C) -- e.g. merged table cells flattened
   * on DOCX import. Empty for documents with nothing to flag. */
  unsupportedFeatures: string[];
}

/** Resolved CSS per formatting target ("Paragraph", "Heading 1", ...), as in Document.resolvedStyles. */
export type ResolvedStyles = Record<string, Record<string, string>>;

export type Alignment = "left" | "center" | "right" | "justify";

/** How one kind of text block looks (backend formatting/style_system.py).
 * null = not set here: the document-wide values, then the engine's defaults, decide. */
export interface TextStyle {
  fontFamily?: string | null;
  fontSizePt?: number | null;
  bold?: boolean | null;
  italic?: boolean | null;
  underline?: boolean | null;
  color?: string | null;
  alignment?: Alignment | null;
  lineSpacing?: number | null;
  spaceAfterPt?: number | null;
  firstLineIndentCm?: number | null;
}

export type HeadingLevel = "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

export type PageSize = "A4" | "Letter" | "Legal";

export interface StyleSystem {
  schemaVersion?: number;
  page: {
    size?: PageSize | null;
    orientation?: "portrait" | "landscape" | null;
    marginTopCm?: number | null;
    marginBottomCm?: number | null;
    marginLeftCm?: number | null;
    marginRightCm?: number | null;
  };
  /** Every text block uses these unless it sets its own (code keeps its own font). */
  document: { fontFamily?: string | null; color?: string | null };
  paragraph: TextStyle;
  headings: Record<HeadingLevel, TextStyle>;
  lists: TextStyle;
  tables: TextStyle;
  captions: TextStyle;
  quotes: TextStyle;
  footnotes: TextStyle;
  code: TextStyle;
  images: { widthPercent?: number | null; alignment?: "left" | "center" | "right" | null };
  header: { text?: string | null };
  footer: { text?: string | null; pageNumbers?: boolean | null };
}

/** The StyleSystem block keys that hold a TextStyle. */
export type TextBlockKey = "paragraph" | "lists" | "tables" | "captions" | "quotes" | "footnotes" | "code";

export type TemplateVisibility = "workspace" | "private";

export interface Template {
  id: string;
  name: string;
  category: string;
  description: string;
  styleSystem: StyleSystem;
  builtin: boolean;
  /** Whether this user may edit, rename or delete it (never for built-ins). */
  editable: boolean;
  isDefault: boolean;
  visibility: TemplateVisibility | null;
  version: number | null;
  sourceDocumentId: string | null;
  updatedAt: string | null;
  /** What each element type resolves to under this template, computed by the backend engine. */
  previewStyles: ResolvedStyles;
}

export interface CreatedTemplate extends Template {
  /** Anything the source document had that the template couldn't carry over. */
  notes: string[];
}

export interface TemplateVersion {
  number: number;
  name: string;
  createdAt: string;
  author: string | null;
  current: boolean;
}

export interface StylePreview {
  resolvedStyles: ResolvedStyles;
  settings: DocumentSettings;
}

export interface FormattingConflict {
  elementId: string;
  property: FormattingProperty;
  currentValue: string;
  currentUnit: string | null;
  requiredValue: string;
  requiredUnit: string | null;
}

export type ConflictResolutionChoice = "apply_recommended" | "keep_current";

export interface StyleFlag {
  elementId: string;
  reason: string;
}

export interface StyleAnalysisResult {
  status: "ok" | "empty_document" | "ai_unavailable";
  consistencyScore: number | null;
  tone: string | null;
  summary: string | null;
  flagged: StyleFlag[];
}

export interface ConflictResolution {
  elementId: string;
  property: FormattingProperty;
  resolution: ConflictResolutionChoice;
}
