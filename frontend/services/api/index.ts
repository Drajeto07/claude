/**
 * The typed API client (корекции.docx §49), one module per part of the API:
 * client.ts (HTTP, errors, request ids), auth.ts, documents.ts (with the
 * per-document write queue and revisions), jobs.ts (background jobs) and
 * templates.ts. Request and response types come from the backend's OpenAPI
 * schema (types/document.ts).
 */
export * from "@/services/api/assets";
export * from "@/services/api/auth";
export * from "@/services/api/client";
export * from "@/services/api/documents";
export * from "@/services/api/jobs";
export * from "@/services/api/templates";
