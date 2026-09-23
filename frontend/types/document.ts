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

export type MarkType = "bold" | "italic" | "strike" | "code" | "link";

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
  src: string;
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
  metadata: DocumentMetadata;
  documentType: string;
  templateId: string | null;
  settings: DocumentSettings;
  sections: Section[];
  elements: Element[];
  formattingRules: FormattingRule[];
  revisions: Revision[];
  resolvedStyles: Record<string, Record<string, string>>;
}

export interface TemplatePreview {
  fontFamily: string | null;
  alignment: string | null;
  lineSpacing: string | null;
}

export interface TemplateSummary {
  id: string;
  name: string;
  category: string;
  description: string;
  preview: TemplatePreview;
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
