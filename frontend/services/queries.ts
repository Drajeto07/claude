"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { getCurrentUser, getTemplate, listTemplates, listTemplateVersions, previewStyleSystem } from "@/services/api";
import type { StyleSystem, Template } from "@/types/document";

/** Every cache key in one place, so an invalidation can't miss one by a typo. */
export const queryKeys = {
  currentUser: ["currentUser"] as const,
  templates: ["templates"] as const,
  template: (id: string) => ["templates", id] as const,
  templateVersions: (id: string) => ["templates", id, "versions"] as const,
  stylePreview: (styleKey: string) => ["stylePreview", styleKey] as const,
  document: (id: string) => ["documents", id] as const,
};

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
