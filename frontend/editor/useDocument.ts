"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { getDocument, rememberRevision, REVISION_CONFLICT_EVENT } from "@/services/api";
import { queryKeys } from "@/services/queries";
import type { Document } from "@/types/document";

/**
 * The document being edited, as server state (корекции.docx §28): the query
 * cache holds the version the server last returned -- the one the page was
 * rendered with, then each change's response. What the editor holds while you
 * type is separate (the Tiptap editor, saved by useAutoSave).
 *
 * `documentRef` always has the latest version, for code that runs after an
 * await. `changedElsewhere` turns on when a write is refused because another
 * tab, window or person changed the document meanwhile.
 */
export function useDocument(initialDocument: Document) {
  const queryClient = useQueryClient();
  const key = queryKeys.document(initialDocument.id);
  const { data: document } = useQuery({
    queryKey: key,
    queryFn: () => getDocument(initialDocument.id),
    initialData: initialDocument,
    // Only this editor changes it (every response lands here), and it starts
    // afresh from the server-rendered version each time the page opens.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });

  const documentRef = useRef(document);
  useEffect(() => {
    documentRef.current = document;
  }, [document]);

  // The page was rendered on the server, so this tab's write queue learns the
  // starting revision here; every later response keeps it current.
  useEffect(() => {
    rememberRevision(initialDocument);
  }, [initialDocument]);

  const [changedElsewhere, setChangedElsewhere] = useState(false);
  useEffect(() => {
    function onConflict(event: Event) {
      if ((event as CustomEvent<{ documentId: string }>).detail.documentId === initialDocument.id) setChangedElsewhere(true);
    }
    window.addEventListener(REVISION_CONFLICT_EVENT, onConflict);
    return () => window.removeEventListener(REVISION_CONFLICT_EVENT, onConflict);
  }, [initialDocument.id]);

  const setDocument = useCallback(
    (updated: Document) => {
      documentRef.current = updated;
      queryClient.setQueryData(queryKeys.document(updated.id), updated);
    },
    [queryClient],
  );

  return { document, documentRef, setDocument, changedElsewhere };
}
