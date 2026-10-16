// End-to-end tests only (playwright.config.ts starts it): the browser's way into the E2E frontend.
//
// The E2E frontend is the production build served over plain HTTP (`next start`), and the production
// Content-Security-Policy says upgrade-insecure-requests. WebKit applies that to localhost too (Chromium and
// Firefox exempt it), so its scripts, styles and API calls went to https://localhost, where nothing listens.
// This proxy passes every request and response through unchanged, except that it removes that one directive
// from the policy header. The app's own policy (frontend/lib/csp.ts, proxy.ts) is not touched.
import http from "node:http";

const listen = Number(process.env.E2E_FRONT_PORT ?? 3100);
const next = { host: "127.0.0.1", port: Number(process.env.E2E_NEXT_PORT ?? 3101) };

function withoutUpgrade(policy) {
  return String(policy)
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part && part.toLowerCase() !== "upgrade-insecure-requests")
    .join("; ");
}

function pass(request, response) {
  const upstream = http.request(
    { ...next, method: request.method, path: request.url, headers: request.headers },
    (answer) => {
      const headers = { ...answer.headers };
      const policy = headers["content-security-policy"];
      if (policy) headers["content-security-policy"] = Array.isArray(policy) ? policy.map(withoutUpgrade) : withoutUpgrade(policy);
      response.writeHead(answer.statusCode ?? 502, answer.statusMessage, headers);
      answer.pipe(response);
    },
  );
  upstream.on("error", () => {
    if (!response.headersSent) response.writeHead(502);
    response.end();
  });
  request.pipe(upstream);
}

// Loopback only, never the network: "localhost" is 127.0.0.1 or ::1 depending on the machine, so both (::1 is
// skipped where the machine has no IPv6).
for (const host of ["127.0.0.1", "::1"]) {
  const server = http.createServer(pass);
  server.on("error", (error) => {
    if (host === "::1" && ["EADDRNOTAVAIL", "EAFNOSUPPORT"].includes(error.code)) return;
    throw error;
  });
  server.listen(listen, host, () => console.log(`E2E front: http://${host.includes(":") ? `[${host}]` : host}:${listen} -> http://${next.host}:${next.port}`));
}
