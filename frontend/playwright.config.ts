import path from "node:path";

import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests (корекции.docx §46): `npm run test:e2e`. Each run starts its
 * own backend on :8100 over a fresh SQLite database (backend/scripts/e2e_server.py,
 * never the real database) and a production build of this app on :3100 built into
 * .next-e2e, then drives a real browser through the workflows in e2e/.
 *
 * The browser: Edge on Windows (installed already, nothing to download), otherwise
 * Playwright's Chromium (`npx playwright install chromium`); E2E_BROWSER_CHANNEL
 * picks another, e.g. "chrome".
 */
const backend = path.resolve(__dirname, "..", "backend");
const python = process.platform === "win32" ? path.join(backend, "venv", "Scripts", "python.exe") : path.join(backend, "venv", "bin", "python");
const channel = process.env.E2E_BROWSER_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined);

export default defineConfig({
  testDir: "e2e",
  // One backend over SQLite: the tests run one at a time.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: "http://localhost:3100",
    channel,
    viewport: { width: 1400, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
  },
  webServer: [
    {
      command: `"${python}" -m scripts.e2e_server`,
      cwd: backend,
      url: "http://127.0.0.1:8100/api/health",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: "npx next build && npx next start --port 3100",
      cwd: __dirname,
      url: "http://localhost:3100",
      timeout: 400_000,
      reuseExistingServer: false,
      env: { NEXT_DIST_DIR: ".next-e2e", NEXT_PUBLIC_API_BASE_URL: "http://localhost:8100" },
    },
  ],
});
