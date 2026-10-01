import type { NextConfig } from "next";

// The Content-Security-Policy is not here: it needs a nonce per request, so
// proxy.ts sets it (SEC-020). These headers are the same for every response.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  // The end-to-end tests build into a folder of their own (playwright.config.ts),
  // so a test run never touches the dev server's or the real build's output.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // The Docker image runs Next's minimal server (.next/standalone/server.js);
  // everywhere else `next start` is used, which standalone output doesn't support.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
