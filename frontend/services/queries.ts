"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  compareVersions,
  getCurrentUser,
  getHealth,
  getTemplate,
  getUsage,
  getVersion,
  listDocuments,
  listJobs,
  listTemplates,
  listTemplateVersions,
  listVersions,
  previewStyleSystem,
  type DocumentListParams,
} from "@/services/api";
import type { StyleSystem, Template } from "@/types/document";

/** Every cache key in one place, so an invalidation can't miss one by a typo.
 * What depends on a document's content carries its revision, so a change
 * made in the editor is followed at once. */
export const queryKeys = {
  currentUser: ["currentUser"] as const,
  templates: ["templates"] as const,
  template: (id: string) => ["templates", id] as const,
  templateVersions: (id: string) => ["templates", id, "versions"] as const,
  stylePreview: (styleKey: string) => ["stylePreview", styleKey] as const,
  document: (id: string) => ["documents", id] as const,
  documentForCompare: (id: string) => ["documents", id, "current"] as const,
  documentList: (params: DocumentListParams) => ["documentList", params] as const,
  allDocumentLists: ["documentList"] as const,
  versions: (id: string, revision: number) => ["documents", id, "versions", revision] as const,
  version: (id: string, number: number) => ["documents", id, "version", number] as const,
  comparison: (id: string, from: number, to: number | undefined, revision: number) => ["documents", id, "compare", from, to ?? "now", revision] as const,
  health: (id: string, revision: number) => ["documents", id, "health", revision] as const,
  usage: ["usage"] as const,
  recentExports: ["recentExports"] as const,
};

/** A page of the user's documents; the previous page stays while the next loads. */
export function useDocumentList(params: DocumentListParams) {
  return useQuery({ queryKey: queryKeys.documentList(params), queryFn: () => listDocuments(params), placeholderData: keepPreviousData });
}

export function useUsage() {
  return useQuery({ queryKey: queryKeys.usage, queryFn: getUsage });
}

export function useRecentExports(limit = 5) {
  return useQuery({ queryKey: queryKeys.recentExports, queryFn: () => listJobs({ type: "export", status: "succeeded", limit }) });
}

export function useVersions(documentId: string, revision: number) {
  return useQuery({ queryKey: queryKeys.versions(documentId, revision), queryFn: () => listVersions(documentId) });
}

/** A version's content never changes, so it is fetched once. */
export function useVersion(documentId: string, number: number | undefined) {
  return useQuery({
    queryKey: queryKeys.version(documentId, number ?? 0),
    queryFn: () => getVersion(documentId, number!),
    enabled: number !== undefined,
    staleTime: Infinity,
  });
}

export function useComparison(documentId: string, from: number, to: number | undefined, revision: number) {
  return useQuery({ queryKey: queryKeys.comparison(documentId, from, to, revision), queryFn: () => compareVersions(documentId, from, to) });
}

export function useHealth(documentId: string, revision: number) {
  return useQuery({ queryKey: queryKeys.health(documentId, revision), queryFn: () => getHealth(documentId) });
}

/** undefined while loading, null when nobody is signed in. */
export function useCurrentUser() {
  return useQuery({ queryKey: queryKeys.currentUser, queryFn: getCurrentUser, staleTime: 5 * 60_000 });
}

/** Built-in and workspace templates; fetched again when the tab regains focus,
 * since the library (often in another tab) may have changed them. */
export function useTemplates() {
  return useQuery({ queryKey: queryKeys.templates, queryFn: listTemplates });
}

export function useTemplate(id: string) {
  return useQuery({ queryKey: queryKeys.template(id), queryFn: () => getTemplate(id), refetchOnWindowFocus: false });
}

export function useTemplateVersions(id: string, enabled: boolean) {
  return useQuery({ queryKey: queryKeys.templateVersions(id), queryFn: () => listTemplateVersions(id), enabled });
}

/** How a style system looks when the real engine resolves it. `styleKey` is its
 * JSON, already debounced by the caller; the last preview stays while the next loads. */
export function useStylePreview(styleSystem: StyleSystem | null, styleKey: string | null) {
  return useQuery({
    queryKey: queryKeys.stylePreview(styleKey ?? ""),
    queryFn: ({ signal }) => previewStyleSystem(styleSystem!, signal),
    enabled: styleSystem !== null && styleKey !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

/** After a template changed: the list, and that template's own entries. */
export function useInvalidateTemplates() {
  const queryClient = useQueryClient();
  return (template?: Template) => {
    if (template) queryClient.setQueryData(queryKeys.template(template.id), template);
    return queryClient.invalidateQueries({ queryKey: queryKeys.templates });
  };
}
