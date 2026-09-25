/**
 * The API's data types. They are generated from the backend's own models
 * (types/generated/api.ts, from the OpenAPI schema backend/scripts/export_openapi.py
 * writes to types/generated/openapi.json), so the backend is their one source
 * of truth and a change there shows up here as a type error, not a runtime
 * surprise. This file only gives them the names the rest of the frontend uses,
 * plus the few types that exist on the frontend alone.
 *
 * Responses use the "-Output" variants: every field the backend always sends is
 * required there. What the frontend builds to send uses the same shapes.
 */
import type { components } from "@/types/generated/api";

type Schemas = components["schemas"];

export type ElementType = Schemas["ElementType"];
export type MarkType = Schemas["MarkType"];
/** textStyle marks (character formatting on part of a paragraph) carry the font
 * fields; null = not set on this run. A highlight is a background colour. */
export type Mark = Schemas["Mark-Output"];
export type InlineRun = Schemas["InlineRun-Output"];
export type ListItem = Schemas["ListItem-Output"];
export type TableCell = Schemas["TableCell-Output"];
export type TableRow = Schemas["TableRow-Output"];
export type TableContent = Schemas["TableContent-Output"];
/** src is empty when assetId is set; otherwise an external URL or a legacy data: URI. */
export type ImageContent = Schemas["ImageContent-Output"];
/** preservedAttributes is the preservation layer (корекции.docx §11): what the
 * editor can't show but a DOCX export puts back ("ooxml": equations, fields,
 * bookmarks, comments). Never read or written by the editor; kept through every save. */
export type Element = Schemas["Element-Output"];
export type FormattingProperty = Schemas["FormattingProperty"];
export type FormattingRule = Schemas["FormattingRule"];
export type DocumentMetadata = Schemas["DocumentMetadata"];
/** pageWidthMm/pageHeightMm: the page's real size for its size and orientation
 * (the backend's render specification). */
export type DocumentSettings = Schemas["DocumentSettings"];
export type Section = Schemas["Section"];
export type Revision = Schemas["Revision"];
/** revision is the concurrency token, sent back as If-Match on every change (services/api). */
export type Document = Schemas["Document"];

/** Resolved CSS per formatting target ("Paragraph", "Heading 1", ...), as in Document.resolvedStyles. */
export type ResolvedStyles = Document["resolvedStyles"];

/** How one kind of text block looks (backend formatting/style_system.py).
 * null = not set here: the document-wide values, then the engine's defaults, decide. */
export type TextStyle = Schemas["TextStyle-Output"];
export type Alignment = NonNullable<TextStyle["alignment"]>;
export type HeadingLevel = keyof Schemas["HeadingStyles-Output"];
export type PageSize = NonNullable<Schemas["PageStyle-Output"]["size"]>;
export type StyleSystem = Schemas["StyleSystem-Output"];
/** The StyleSystem block keys that hold a TextStyle. */
export type TextBlockKey = "paragraph" | "lists" | "tables" | "captions" | "quotes" | "footnotes" | "code";

export type TemplateVisibility = Schemas["TemplateVisibility"];
/** previewStyles: what each element type resolves to under this template, computed
 * by the backend engine. editable: whether this user may edit, rename or delete it. */
export type Template = Schemas["TemplateOut"];
/** notes: anything the source document had that the template couldn't carry over. */
export type CreatedTemplate = Schemas["CreatedTemplateOut"];
export type TemplateVersion = Schemas["TemplateVersionOut"];
export type StylePreview = Schemas["StylePreviewOut"];

/** A background job (backend app/jobs): heavy work done off the request, polled
 * for its real stage and progress (never a timer). */
export type Job = Schemas["JobOut"];
export type ImportJobResult = Schemas["ImportJobResult"];
export type FormatJobResult = Schemas["FormatAppliedResult"] | Schemas["FormatConflictsResult"];
export type ExportJobResult = Schemas["ExportJobResult"];
/** What a job-backed call reports while it runs. */
export type JobProgress = { stage: string; progress: number };

/** Format by Example: the look a reference Word document uses, read by the
 * backend. Not saved until it becomes a template. */
export type ReferenceStyle = Schemas["ReferenceStyleOut"];

export type FormattingConflict = Schemas["FormattingConflict"];
export type StyleFlag = Schemas["StyleFlag"];
export type StyleAnalysisResult = Schemas["StyleAnalysisResponse"];
export type CurrentUser = Schemas["UserResponse"];

/** A document in the list and on the dashboard (not its content). */
export type DocumentSummary = Schemas["DocumentSummaryOut"];
export type DocumentList = Schemas["DocumentListOut"];
/** One kept version of a document; `current` is the one it shows now. */
export type DocumentVersion = Schemas["DocumentVersionOut"];
/** What changed between two versions (before/after). */
export type DocumentComparison = Schemas["DocumentComparison"];
export type ElementChange = Schemas["ElementChange"];
export type StyleChange = Schemas["StyleChange"];
export type SettingChange = Schemas["SettingChange"];
/** Document Health: deterministic checks and the score from them. */
export type HealthReport = Schemas["HealthReport"];
export type HealthCheck = Schemas["HealthCheck"];
/** This month's usage of the workspace, and what it stores. */
export type Usage = Schemas["UsageOut"];

/** The body of every error response (backend app/api/errors.py). */
export type ApiErrorBody = Schemas["ApiError"];

// Sent as a JSON string in a form field, so the OpenAPI schema doesn't describe it
// (backend schemas/formatting.py ConflictResolutionInput).
export type ConflictResolutionChoice = "apply_recommended" | "keep_current";
export interface ConflictResolution {
  elementId: string;
  property: FormattingProperty;
  resolution: ConflictResolutionChoice;
}
