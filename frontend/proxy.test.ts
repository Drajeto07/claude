import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy } from "./lib/csp";
import { proxy } from "./proxy";

const API = "https://api.example.com";

function directive(policy: string, name: string): string {
  return policy.split("; ").find((part) => part.startsWith(`${name} `)) ?? "";
}

function nonceIn(policy: string): string {
  return /'nonce-([^']+)'/.exec(directive(policy, "script-src"))![1];
}

describe("buildContentSecurityPolicy", () => {
  it("lets scripts run only by nonce, never inline or by eval in production", () => {
    const script = directive(buildContentSecurityPolicy({ nonce: "abc", apiOrigin: API, isDev: false }), "script-src");
    expect(script).toBe("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(script).not.toContain("unsafe-inline");
    expect(script).not.toContain("unsafe-eval");
  });

  it("allows eval in development only, and never inline scripts", () => {
    const script = directive(buildContentSecurityPolicy({ nonce: "abc", apiOrigin: API, isDev: true }), "script-src");
    expect(script).toContain("'unsafe-eval'");
    expect(script).not.toContain("unsafe-inline");
  });

  it("keeps style elements on the nonce and unsafe-inline for style attributes only", () => {
    const policy = buildContentSecurityPolicy({ nonce: "abc", apiOrigin: API, isDev: false });
    expect(directive(policy, "style-src")).toBe("style-src 'self' 'nonce-abc'");
    expect(directive(policy, "style-src-attr")).toBe("style-src-attr 'unsafe-inline'");
  });

  it("keeps the other directives: the API origin, pictures, no framing, no plugins", () => {
    const policy = buildContentSecurityPolicy({ nonce: "abc", apiOrigin: API, isDev: false });
    expect(directive(policy, "connect-src")).toBe(`connect-src 'self' ${API}`);
    expect(directive(policy, "img-src")).toBe(`img-src 'self' data: blob: ${API}`);
    expect(directive(policy, "default-src")).toBe("default-src 'self'");
    expect(directive(policy, "frame-ancestors")).toBe("frame-ancestors 'none'");
    expect(directive(policy, "object-src")).toBe("object-src 'none'");
    expect(directive(policy, "base-uri")).toBe("base-uri 'self'");
    expect(directive(policy, "form-action")).toBe("form-action 'self'");
    expect(policy).toContain("upgrade-insecure-requests");
  });
});

describe("proxy", () => {
  it("sets the policy on the response with a fresh nonce each time", () => {
    const first = proxy(new NextRequest("http://localhost:3000/login"));
    const second = proxy(new NextRequest("http://localhost:3000/login"));
    const a = first.headers.get("content-security-policy")!;
    const b = second.headers.get("content-security-policy")!;

    expect(nonceIn(a)).not.toBe(nonceIn(b));
    expect(nonceIn(a).length).toBeGreaterThanOrEqual(22);
    expect(directive(a, "script-src")).not.toContain("unsafe-inline");
    expect(directive(a, "script-src")).not.toContain("unsafe-eval");
  });

  it("passes the same policy and nonce on to the render through the request headers", () => {
    const response = proxy(new NextRequest("http://localhost:3000/documents"));
    const policy = response.headers.get("content-security-policy")!;
    // NextResponse.next({ request }) carries the changed request headers as x-middleware-request-*.
    expect(response.headers.get("x-middleware-request-content-security-policy")).toBe(policy);
    expect(response.headers.get("x-middleware-request-x-nonce")).toBe(nonceIn(policy));
  });
});
