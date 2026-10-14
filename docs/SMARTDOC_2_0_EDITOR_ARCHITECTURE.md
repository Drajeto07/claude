# SmartDoc 2.0 Editor -- architecture and plan (P4/P5)

Status: **proposal for the owner's review** (2026-10-14). Nothing here replaces the 1.x editor yet; the work
below is staged so every step ships behind a switch, keeps every existing document and export working, and
is covered by tests before the next one starts.

## 1. Starting point (what exists and must keep working)

| Piece | Where | Keep / change |
| --- | --- | --- |
| Document model (elements, formatting rules, styles, sections, preserved OOXML) | `backend/app/models/document.py` | **Keep** -- the single source of truth for both modes; extended additively (section 4) |
| Deterministic formatting engine, templates, style systems | `backend/app/formatting/*` | Keep |
| DOCX / PDF export, fidelity report, round-trip tests | `backend/app/export/*`, golden fixtures | Keep; design mode adds its own export path (section 9) |
| Text engine: Tiptap/ProseMirror + converters | `frontend/editor/documentToTiptap.ts`, `tiptapToDocument.ts` (~1,100 lines, round-trip tested) | **Keep** as the Document Mode text engine |
| Real pages in the flow | `frontend/editor/pagination.ts`, `sectionPages.ts` | Keep |
| Autosave: debounced PATCH /content with revision, retries, offline, conflict | `frontend/editor/useAutoSave.ts`, `contentPatch.ts` | Keep; extend the patch for design items |
| Panels (templates, structure, history, health, translate, review, page settings, properties) | `frontend/editor/panels/*` | Re-housed in the new shell, restyled on the 2.0 tokens and dictionaries |
| Shell (toolbar row, side rail, action bar, status bar) | `DocumentEditorShell.tsx`, `EditorToolbar.tsx`, `SidePanel.tsx` | **Replaced** by the 2.0 shell (section 3) |

Rewriting the text engine would throw away the most tested part of the product for no user gain. The 2.0
editor is a new **shell and interaction layer** around it, plus a **new design-mode model** for positioned
elements.

## 2. Two modes, one document

- **Document Mode** -- the content is a flow: headings, paragraphs, lists, tables, pictures, laid out onto
  real pages (A4/Letter/...). Text reflows; pages are computed. Every existing document opens here, unchanged.
- **Free Design Mode** -- the content is pages of fixed size (A4, 16:9, square, poster...) holding
  **positioned items**: text boxes, pictures, shapes, lines, groups, each with x/y/width/height/rotation and
  a stacking order. Nothing reflows between items; text reflows inside its own box.

A document has one kind (`Document.kind`, default `"flow"`; D-006). New Project picks it (Document → flow;
Poster/Invitation/Presentation/Free design → design). Converting flow → design ("place this page on a
canvas") is a later, explicit action that makes a copy; there is no silent conversion.

## 3. The shell (both modes)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ ◂ Projects   Title (editable)   Saved ✓        Undo Redo   Zoom ▾   Share  Export │  top bar (48px)
├──────┬────────────┬───────────────────────────────────────────────┬────────────┤
│ rail │ left panel │              canvas (centred page(s))          │ properties │
│ 56px │ 280px      │      contextual toolbar floats above selection │ 300px      │
│      │ (closable) │                                                │ (closable) │
├──────┴────────────┴───────────────────────────────────────────────┴────────────┤
│ page n / N · words · zoom slider · fit width                                     │  status bar
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Rail + left panel**: Elements (insert text/heading/list/table/picture/shape/line), Pages (thumbnails;
  in design mode add/duplicate/reorder/delete), Structure (the outline; section reorder and heading levels
  reuse `structureEdits.ts` from the creation flow), Templates, Translate (S2-070), History, Health.
  One panel open at a time; the canvas widens when it closes.
- **Canvas**: grey working area, white paper in both themes (a document prints white), centred, zoom
  25-400 % (fit width / fit page / 100 %), smooth scroll between pages. At 1440 px (measured in E1): about
  75 % of the width with only the properties open, about 57 % with a left panel open too -- both panels can
  be closed for the full width; panels collapse to overlays below 1100 px; on phones the editor is
  read-mostly with a bottom sheet for properties (full editing on phones is out of the first release).
- **Contextual toolbar**: a floating bar anchored to the selection, its controls chosen by selection type
  (section 6). The top bar keeps only document-wide actions.
- **Properties panel**: what the selection is and every property it has (typography, spacing, colour,
  border, position/size in design mode); with nothing selected, the page and the document.
- All copy in `frontend/i18n` (EN/BG); light theme standard, dark optional, tokens only.

## 4. Data model additions (additive, JSON only)

Documents are stored as JSON (`documents.data`); new fields are optional with defaults, so every stored
document stays valid and no SQL migration is needed.

```python
class Document:            # existing model, two new optional fields
    kind: Literal["flow", "canvas"] = "flow"   # D-006
    canvas: Optional[DesignCanvas] = None      # only for kind == "canvas"

class DesignCanvas:
    pages: list[DesignPage]

class DesignPage:
    id: str
    widthMm: float; heightMm: float            # or px for screen formats, stored as mm + dpi hint
    background: Optional[str]                  # colour; picture backgrounds via an item locked at z=0
    items: list[DesignItem]

class DesignItem:
    id: str
    kind: Literal["text", "image", "shape", "line", "group"]
    x: float; y: float; width: float; height: float   # mm, page coordinates, top-left origin
    rotation: float = 0                                # degrees, around the centre
    z: int                                             # stacking order within the page
    locked: bool = False
    text: Optional[list[Element]]              # a text item holds ordinary blocks: same runs/marks/styles
    image: Optional[ImageContent]              # existing asset model (DocumentAsset), crop/flip reused
    shape: Optional[ShapeStyle]                # rect/ellipse/triangle..., fill, stroke, radius
    children: Optional[list[DesignItem]]       # group
```

Text inside a design item **is the existing `Element` list**, so formatting rules, templates, translation,
health checks and the DOCX text writer apply to it unchanged.

**Owner decision needed before anything in design mode is saved from the Preview (D-012):** the 2.0
Preview shares the production database (D-004). Checked 2026-10-14: the 1.x model (`ApiModel`, pydantic
default `extra="ignore"`) would **open** a design document without error but **drop `kind` and `canvas`
when it saves it** -- a design document opened and edited in production would silently lose its canvas.
So either (a) give the 2.0 Preview its own database (recommended), or (b) promote a small 1.x change that
keeps unknown fields (`extra="allow"` on `Document`, with a round-trip test) before any design document is
written to the shared database. Until then design mode runs on local throwaway servers and in tests only.

## 5. Selection and manipulation model

One **selection state** for both modes: `{ kind: "none" | "text" | "block" | "items" | "page", ids, range? }`.

- **Document Mode** -- hover outlines the block under the pointer; a click selects the block (ProseMirror
  NodeSelection for pictures/tables, a block selection mode for text blocks) and fills the properties panel;
  a double-click or typing places the caret (text selection). Esc goes up one level (text → block → none).
  Pictures get resize handles (existing `pictureEdit.ts`).
- **Free Design Mode** -- a pure reducer (`frontend/editor/design/model.ts`) owns items and selection:
  click selects, Shift-click adds/removes, drag on empty canvas draws a marquee; dragging moves; 8 handles
  resize (Shift keeps proportions, Alt from the centre); a rotation handle rotates (Shift snaps to 15°);
  arrow keys nudge 1 px (Shift 10 px); Delete removes; Ctrl/Cmd+D duplicates; [ and ] change stacking;
  Ctrl/Cmd+G groups. **Snapping** to page edges/centre, other items' edges/centres and equal spacing, with
  guides drawn while dragging (threshold 4 screen px, independent of zoom). Double-click a text item edits
  its text in place with a small ProseMirror instance (the same extensions as Document Mode).
- Rendering: items are absolutely positioned HTML (text) / img / SVG (shapes) in a page box scaled by zoom;
  handles and guides on a separate overlay layer so they never reach exports.

The reducer is pure (state, action) → state: every behaviour above is unit-tested without a browser, and
the same actions back keyboard shortcuts, toolbar buttons and the properties panel.

## 6. Contextual toolbar and commands

A **command registry**: each command has an id, label key, icon, shortcut, `isAvailable(selection)`,
`isActive(selection)`, and `run(selection, ...)`. Toolbar, properties panel, shortcuts and the menu all read
it, so a command behaves the same everywhere and is tested once.

| Selection | Toolbar |
| --- | --- |
| Text (caret/range) | style (Heading 1-3 / body), font, size, B I U S, colour, highlight, align, list, link, clear formatting |
| Block (flow) | block type, align, spacing, move up/down, delete |
| Picture | replace, crop, flip/turn, size, wrap (flow) / position (design), alt text |
| Table | rows/columns, header row, borders, cell background |
| Shape/line (design) | fill, stroke, width, corner radius, opacity |
| Several items (design) | align (left/centre/right/top/middle/bottom), distribute, group, stacking |
| Page | size, orientation, margins (flow) / background (design) |

## 7. Undo / redo

- **Document Mode** keeps ProseMirror's history for typing, and today's server-side formatting undo for
  template/instruction application. The 2.0 shell shows **one** Undo/Redo pair that routes to whichever
  history holds the newest step (a small coordinator records the order of local and server steps).
- **Free Design Mode**: the reducer keeps a bounded history (200 steps) of inverse patches; a drag, resize
  or rotate is one step (coalesced on pointer-up); typing inside a text item is coalesced per pause.
- Saved versions (DocumentVersion, restore, compare) stay as they are, for both modes.

## 8. Autosave

The existing `useAutoSave` stays: debounced (1.2 s) PATCH with the revision, retries with back-off, offline
detection, conflict handling, status in the top bar ("Saving…", "Saved", "Offline -- will retry",
"Changed elsewhere"). The patch gains design operations (`items: { changed, added, removed }` per page);
the backend applies them in `patch_content` the same way it applies element changes. Recovery after a
refresh or an expired session: unsent changes are kept in IndexedDB per document and offered back.

## 9. Compatibility and export

- Every existing document is `kind: "flow"` and opens in the new shell exactly as in 1.x; the golden
  DOCX round-trip fixtures and every Playwright workflow must pass on the new shell **before** it becomes
  the default (section 11).
- **Flow export** (DOCX/PDF) is unchanged.
- **Design export**: PDF first (absolute positioning in the existing PDF writer; fonts embedded as today),
  PNG/JPG per page (server render via the thumbnail renderer's pipeline), then DOCX with each item as an
  anchored drawing/text box (`TEXT_BOX` support from DOCX-019A is the starting point). What can't be kept
  exactly is listed in the fidelity report, never silently dropped.

## 10. Testing

- Unit: design reducer (select, move, resize with/without aspect lock, rotate, nudge, snap, z-order, group,
  history), geometry, command availability, undo coordinator.
- Component: toolbar per selection type, properties panel, panels in both languages and themes.
- E2E: every existing workflow on the new shell; new ones for design mode (place, move, resize, type,
  undo, reload keeps it, export PDF).
- Regression gates: golden DOCX fixtures, export verification, typing latency budget (perf-typing spec),
  axe accessibility on the shell.

## 11. Milestones

| # | Milestone | Ships | Gate |
| --- | --- | --- | --- |
| E0 | This plan | doc | owner review |
| E1 | 2.0 shell around the current canvas: top bar, rail + left panel, centred zoomable canvas, properties panel, status bar; panels re-housed | behind `?editor=2` (per-user switch later) | all Vitest + E2E on both shells |
| E2 | Selection model + command registry + contextual toolbar in Document Mode | behind switch | new unit/E2E tests |
| E3 | Design model: reducer + geometry + snapping (pure, tested) and read-only rendering | lab page on local servers | reducer test suite |
| E4 | Design interactions: drag/resize/rotate/snap/nudge/multi-select/group + undo | lab page | E2E on local servers |
| E5 | Design text editing, Elements and Pages panels | lab page | E2E |
| E6 | Persistence (needs D-012) + design autosave + PDF/PNG export, then DOCX | behind switch | export tests, round trip |
| E7 | New shell becomes the default once every gate is green; old shell kept one release as fallback | default | owner approval |

Safe foundations started now (no effect on users): E3's pure design model with its tests.
