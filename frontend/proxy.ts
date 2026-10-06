import { NextResponse, type NextRequest } from "next/server";

import { buildContentSecurityPolicy, generateNonce } from "./lib/csp";

// Where the app's data and stored images come from (inlined at build time, like
// in the browser's own API client).
const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").origin;
const isDev = process.env.NODE_ENV === "development";

/**
 * Next.js 16's "proxy" (formerly middleware): gives every page request its own
 * nonce and Content-Security-Policy (SEC-020). The policy goes on the request too,
 * because Next reads the nonce from it while rendering and stamps it on its
 * scripts and styles; the layout reads `x-nonce` for the editor's own style tag.
 */
export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const policy = buildContentSecurityPolicy({ nonce, apiOrigin, isDev });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: the built files under /_next/static and /_next/image are
      // static, and next/link prefetches carry no page that could use a nonce.
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
