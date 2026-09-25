# Target state

The architecture SmartDoc Formatter is moving toward — a production-ready, multi-tenant SaaS document-transformation platform. This describes the **destination**; `docs/architecture/migration-plan.md` describes the path from `current-state.md` to here, phase by phase. Source: `корекции.docx` (94-section specification, kept in the project root).

## Product identity

Not a general word processor. The product's core promise stays: **"Format my document without changing my content."** Its two flagship capabilities:
1. **Standard formatting** — upload/paste → AI-assisted structure analysis → deterministic formatting (template, instructions, or both) → review → export.
2. **Format by Example** — upload a document *and* a reference/template document; the system extracts the reference's `StyleSystem` and applies it to the target, content untouched.

Three product modes: **Quick Format** (fastest path), **Advanced Format** (templates/instructions/conflict handling), **Format by Example**.

## Architecture

```
Frontend (Next.js)
├── App / Authentication
├── Dashboard
├── Document creation
├── Document editor
├── Template management
├── Workspace / Team
└── Billing / Usage
        │
        ▼
API v1 (versioned, replaces unversioned /api/...)
├── Auth · Users · Workspaces · Documents · Templates
├── Formatting · Analysis · Jobs · Exports · Billing
        │
        ▼
Application Services (dependency-injected, not one singleton)
├── Document Service        ├── AI Service
├── Ingestion Service        ├── Export Service
├── Formatting Service        ├── Storage Service
├── Template Service        ├── Revision Service
└── Billing Service
        │
   ┌────┼──────────┬────────────┬──────────────┐
   ▼    ▼          ▼            ▼              ▼
PostgreSQL   Object Storage   Redis/Queue   AI Provider
             (S3-compatible)  (arq)         (Anthropic, swappable)
        │
        ▼
Workers (arq): AI analysis · parsing · exports · heavy processing
```

## Database (PostgreSQL + SQLAlchemy 2.x async + Alembic)

Core tables: `User`, `Workspace`, `WorkspaceMember` (roles: owner/member), `Session`, `Document`, `DocumentVersion`, `DocumentAsset`, `Template`, `TemplateVersion`, `FormattingProfile`, `ProcessingJob` (every kind of background job; the separate `ExportJob` the spec lists was folded into it in Phase 11, since an export is one kind of job), `Subscription`, `UsageRecord`. Every `Document` has an owning `Workspace`; every document-touching endpoint is `authenticate → authorize (workspace membership) → fetch` — a UUID is never itself a security boundary.

## Document fidelity

The canonical model must, for every feature a real uploaded document can contain, do one of exactly three things — never a fourth ("delete silently"):
- **A. Fully supported** (edit + export round-trip correctly): text, bold/italic/underline/strike, headings, paragraphs, basic lists/tables, images, page size/margins/orientation, page breaks, page numbers, hyperlinks, captions.
- **B. Preserved but not editable yet**: complex numbering, unsupported run properties, bookmarks, comments/tracked-changes metadata, footnotes/endnotes where technically feasible — carried through an explicit preservation layer (opaque OOXML fragments attached to the model) rather than dropped.
- **C. Explicitly unsupported, flagged before processing**: equations, scanned/image-only PDF layout reconstruction — the UI says so up front, never a silent gap discovered later.

## StyleSystem

A product-level representation sitting above raw `FormattingRule` entries — `{ document, page, paragraph, headings: {h1,h2,h3}, lists, tables, captions, header, footer, images }`. Presets (Academic, Corporate, Legal, CV, Modern Report, University, Custom) are `StyleSystem` instances, not ad-hoc Python-file rule lists. `FormattingRule` remains the internal application mechanism the deterministic engine consumes; `StyleSystem` is what templates, Format-by-Example, and presets are actually made of.

## Auth & multi-tenancy

Server-side sessions in secure HTTP-only cookies (never a token in `localStorage`), argon2 password hashing, CSRF protection where relevant, session expiry/revocation. `User → Workspace → Documents`, owner/member roles now, architecture left open for a fuller RBAC later without a rewrite.

## Assets

`DocumentAsset` (id, mime_type, width, height, alt_text, metadata) backed by a `StorageProvider` abstraction (`LocalStorageProvider` for dev, `S3StorageProvider`/MinIO-compatible for anything real) — never a base64 blob inside the document JSON. Fixes memory pressure, huge JSON payloads, and undo-snapshot duplication at the root.

## Revisions & concurrency

Editor undo/redo (client-side, ProseMirror-native where it fits) is explicitly separate from server-side `DocumentVersion` history, which is persisted, bounded, restorable, and auditable — never an unbounded deep-copy stack. Optimistic concurrency via a document revision number: a stale client write becomes a surfaced conflict, never a silent last-write-wins.

## AI architecture

Provider abstraction stays and becomes swappable in practice (Anthropic today, OpenAI or another provider without touching business logic). Explicit task separation: Structure Analysis, Instruction Extraction, Style Analysis, Style Mapping (for Format by Example), optional Document Classification. No task is ever "rewrite the document." Every AI call has schema validation, retries, timeout, token budget, telemetry, and a defined error/fallback state. Large documents are chunked (stable IDs per chunk, merged results, global consistency validation) instead of one unbounded prompt. Prompts strictly separate system instructions / user formatting instructions / document content — document content is always untrusted data, never treated as instructions.

## Export

One shared **Document Render Specification** feeds DOCX, PDF, and preview rendering — page size/margin/spacing constants live in exactly one place, not three. DOCX export prefers native Word semantics (styles, numbering definitions, section properties) over inline-CSS-only mapping. PDF gets real font embedding instead of collapsing everything to Helvetica/Times/Courier.

## Background processing

Heavy work (AI calls, parsing, exports, high-fidelity rendering) runs in `arq` workers against Redis, never blocking the request thread. Jobs carry `id/status/progress/type/document_id/timestamps/error`; the frontend shows real states (Uploading/Analyzing/Parsing/Formatting/Rendering/Finalizing/Complete/Failed), never a fake progress bar. Done in Phase 11: development runs the same jobs in the API process (`JOB_BACKEND=background`), production in the worker (`JOB_BACKEND=arq`); job files and old jobs are swept hourly and unused images daily.

## Billing

Stripe-backed `Subscription` + a plan-independent `Entitlements` service (`can_export_docx`, `max_documents`, `max_ai_operations`, `max_storage`, ...). Business logic checks entitlements, never `if plan == "pro"` scattered through the codebase. Real pricing/plan definitions are a business decision made when Phase 14 starts, not assumed here.

## Testing

Backend: the existing 179 tests plus migration tests, security tests, and — critically — a golden-document fixture suite (`fixtures/documents/*.docx`) run through real upload → parse → edit → format → export → re-import → compare, closing the gap that today's round-trip tests only exercise synthetically-constructed documents. Frontend: Vitest + React Testing Library (currently zero coverage) plus Playwright E2E for the full user-facing workflow.

## Deployment

Dockerfiles for both services, `docker-compose.yml` wiring frontend/backend/postgres/redis/minio for local dev, GitHub Actions CI (tests/typecheck/lint/build/migration-check on every PR), health/readiness endpoints, and a real production ASGI setup — `fastapi dev` never runs in production.
