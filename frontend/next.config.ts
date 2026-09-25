import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
// Where the app's data and stored images come from (services/api/client.ts).
const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").origin;

// Content-Security-Policy (корекции.docx §33), set here rather than with per-request
// nonces so pages can stay static: Next.js's small inline bootstrap scripts need
// 'unsafe-inline', and the editor's inline styles need it for style-src. Everything
// else is limited to this site and the API. React needs 'unsafe-eval' in
// development only; the dev server's hot reload talks over a WebSocket.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${apiOrigin}`,
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}${isDev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
