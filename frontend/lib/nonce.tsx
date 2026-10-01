"use client";

import { createContext, useContext, type ReactNode } from "react";

const NonceContext = createContext<string | undefined>(undefined);

/** The page's CSP nonce (from proxy.ts, via the layout), for the few client
 * components that add a <style> element themselves: Tiptap's editor CSS. */
export function NonceProvider({ nonce, children }: { nonce: string | undefined; children: ReactNode }) {
  return <NonceContext.Provider value={nonce}>{children}</NonceContext.Provider>;
}

export function useNonce(): string | undefined {
  return useContext(NonceContext);
}
