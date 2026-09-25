"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/services/api";

/** Server state lives in TanStack Query's cache (корекции.docx §28); what the
 * editor holds while you type stays local to it. One client per browser tab. */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // An answer like "not found" won't change on a retry; a network hiccup might.
            retry: (failures, error) => failures < 2 && !(error instanceof ApiError && error.status < 500),
          },
        },
      }),
  );
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
