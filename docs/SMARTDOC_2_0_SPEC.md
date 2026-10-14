# SmartDoc 2.0 -- specification and architecture

The owner's master directive (2026-10-13) in engineering terms. Product language with the owner: Bulgarian; code
and these docs: English. Status of every item: `docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx` (built from
`docs/SMARTDOC_2_0_TRACKER.json`). Decisions: `SMARTDOC_2_0_DECISIONS.md`. Where we are: `SMARTDOC_2_0_SESSION_STATE.md`.

## 1. Product

A universal, AI-assisted document **and** visual-design editor: Word's structure (flowing multi-page documents,
styles, headings, tables, export) with a modern, Canva-inspired visual editor (free canvas, templates, layers),
and an AI assistant that only ever **proposes** -- the user approves every change. Translation is a first-class
feature. Use cases: academic papers, reports, CVs, contracts, brochures, flyers, posters, invitations, menus,
presentations, social posts, free compositions.

## 2. Baseline (what SmartDoc 1.x already is -- audited 2026-10-13)

| Area | What exists (reused) |
| --- | --- |
| Frontend | Next.js 16 App Router, React 19, Tailwind v4, TanStack Query, Tiptap/ProseMirror editor (`frontend/editor/`, ~60 modules: paged canvas, rich-text toolbar, outline, properties, autosave, undo/redo, export menu), dashboard, create-document wizard (paste/upload -> analyze -> format), template library + editor, settings, compare view |
| Backend | FastAPI `/api/v1`: auth (sessions, cookies), documents (Document Model JSON in Postgres JSONB, revisions, versions), assets (S3), jobs (import/format/export/translate; eager on Vercel), templates (StyleSystem), billing/entitlements, health/fixes, translation (provider abstraction) |
| Data | Supabase Postgres (transaction pooler), Supabase Storage S3 bucket `smartdoc-files` |
| Hosting | One Vercel project, services (Next.js at `/`, API container at `/api/*`), fra1, behind Vercel Authentication |
| Quality | backend 2599 tests, Vitest 368, Playwright 59, golden Word fixtures |

Gaps against the vision: no design system (3 colours, Latin-only font), no project types, no free canvas, no
element-level selection model beyond text, AI proposals exist only for some operations, translation UI is a
document-level job without a review screen, UI copy is English only.

## 3. Architecture decisions that shape everything

1. **Two document kinds, one store.** `documents.data` (JSONB) keeps the existing *flow* Document Model for Document
   Mode. Free Design adds a *canvas* model -- pages of a fixed size holding absolutely positioned elements (text
   box, image, shape, table), with z-order, groups, rotation -- stored in the same column with a `kind` discriminator
   and `schema_version`. No new tables are needed for it; old documents read as `kind = "flow"` by default (an
   adapter, not a migration). Exports dispatch on kind.
2. **Document Mode stays Tiptap.** Paragraphs never become free-positioned boxes (reflow and Word export depend on
   it). Images/text boxes may float within the flow where the model already supports it.
3. **Free Design is a separate canvas editor** sharing the shell, panels, toolbar components and selection model,
   rendered as positioned DOM (not a bitmap), so text stays editable and translatable.
4. **AI = proposals.** Every AI action returns a proposal (a patch against a revision) shown as a preview/diff;
   accept applies it as a normal revision (undoable), reject changes nothing. The backend already has this pattern
   for some operations (review/repair proposals); it is generalised, not reinvented.
5. **Translation works on segments** of the structured model (runs inside blocks / text boxes) and writes back into
   the same structure, never flattening; it produces a new document by default and reports overflow per page/box.
6. **Isolation:** 2.0 lives on `feature/smartdoc-2.0` and its Preview; Production stays 1.x until an approved
   promote. The 2.0 Preview shares the production database and bucket (Vercel Preview settings), so **no schema
   change and no destructive data operation is made from 2.0 without approval** (D-004).

## 4. Design system (approved direction, original -- no Canva assets)

White and light-neutral surfaces; blue (`#2563eb`-ish) to purple (`#7c3aed`-ish) accents; Inter (Latin + Cyrillic);
rounded controls (8-12 px), subtle borders and shadows, spacious layout; a central canvas, left navigation/element
panels, right properties panel, contextual top toolbar, optional AI panel. Tokens live in `frontend/app/globals.css`
(`@theme`), primitives in `frontend/components/ui/`. Accessible: visible focus, 4.5:1 text contrast, keyboard paths.

## 5. Screens (approved concept) and flows

1. Login / Registration -- honest (no social buttons, no password reset while e-mail is off), sessions persist.
2. Dashboard -- Create Project, recent/all projects with thumbnails, search, type and last-edited, templates, AI entry.
3. New Project -- types: Document, Free Design, CV, Presentation, Brochure, Invitation, Poster, From Template, Create
   with AI ("Describe what you want to create..."); manual choice always possible.
4. Add Content -> 5. AI Structure Review -> 6. Style / Template -> 7. Visual Editor (Document flow).
   Blank document skips 4-6. Free Design: type -> canvas size/template -> editor.

### 5.1 Document creation flow (P3, S2-020) -- design 2026-10-14

Today `/new` (`CreateDocumentWizard`) asks for the template first, then the content, then how to format, and only
then imports and shows a read-only outline. 2.0 puts the content first and the look last, in one guided flow that
replaces the wizard at the same address, `/new` -- every link and its parameters (`?template=`, `?mode=upload`,
`?reference=1`) keep working:

1. **Add content** -- paste text, or upload TXT/DOCX/PDF (PDF: editable vs layout; DOCX: autolink). Limits from the
   plan's entitlements. Copy says what is read how: Word files as they are, plain text analysed for structure.
2. **Analyse** -- the existing import job (`importText`/`importFile`) with its real stages; nothing simulated.
3. **Review the structure** -- the outline that import produced, with the confidence the analysis recorded, and edits
   the user confirms before anything is formatted: project title (`renameDocument`); a block as Heading 1/2/3 or as
   body text; move a section (a heading and what follows it, up to the next heading of the same or a higher level)
   up or down. Edits are kept in the page until "Confirm structure" and saved once with `PUT /content`
   (`updateContent`, styles `[]` = formatting untouched, `If-Match` revision); no text is rewritten, no new endpoint,
   no schema change. Tracked-changes choice stays here for Word files that have them.
4. **Choose the look** -- template cards with a live sample (default preselected; `?template=` from the dashboard),
   "Match a reference document" (Format by Example), "AI instructions" (only labelled AI when a provider is
   configured -- otherwise it says the rules-based fallback is used), or "Decide later".
5. **Editor** -- `formatDocument` job (real progress), then `/documents/{id}`.

Leaving after step 2 keeps the imported document as a draft (it is already saved): the dashboard shows it and the
editor opens it. All copy is in `frontend/i18n` (EN/BG).

## 6. Editor interactions (progressive)

Hover outline, click select (handles), double-click text edit, click-out deselect; drag, resize, snap/alignment
guides, keyboard nudge (canvas); contextual toolbar by selection type (text / image / shape); properties panel;
undo/redo, shortcuts, autosave with visible state, recovery after refresh/session expiry.

## 7. Page / canvas sizes (first set)

A4, A5, US Letter, 16:9 (1920x1080), Square (1080x1080), Portrait social (1080x1350), Poster A3, custom. Units:
mm for print, px for screen formats; export at the real size.

## 8. AI and translation providers

Anthropic is wired (`ANTHROPIC_API_KEY`, not set on Vercel: AI steps use their deterministic fallbacks). Translation
has a provider abstraction (pseudo provider in tests). Enabling a paid provider needs the owner's approval with cost
and privacy notes (D-007). Nothing is presented as AI that is a heuristic.

## 9. Non-goals for the first 2.0 release

Full Canva parity, real-time collaboration, social login, pixel-perfect export claims, public sign-up (blocked on
real e-mail and verified isolation).
