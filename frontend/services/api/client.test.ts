import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, errorFrom, errorMessage, jsonInit, NetworkError, PLAN_LIMIT_EVENT, UnauthorizedError } from "./client";

function response(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("errors from the API", () => {
  it("carry the backend's message, code, details and request id", async () => {
    const error = await errorFrom(
      response(412, { code: "revision_conflict", message: "Changed elsewhere.", details: { currentRevision: 7 }, request_id: "req-1" }),
      "Save failed",
    );

    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message, error.details, error.requestId]).toEqual([
      412,
      "revision_conflict",
      "Changed elsewhere.",
      { currentRevision: 7 },
      "req-1",
    ]);
  });

  it("fall back to a message of their own when the body says nothing", async () => {
    const error = await errorFrom(new Response("<html>bad gateway</html>", { status: 502, headers: { "X-Request-ID": "req-2" } }), "Save failed");

    expect([error.message, error.code, error.requestId]).toEqual(["Save failed (502)", "error", "req-2"]);
  });

  it("announce a plan limit, so the page can offer the plans", async () => {
    const heard: string[] = [];
    const listener = (event: Event) => heard.push((event as CustomEvent<string>).detail);
    window.addEventListener(PLAN_LIMIT_EVENT, listener);
    try {
      await errorFrom(response(402, { code: "plan_limit", message: "Your plan allows 25 documents." }), "Create failed");
      await errorFrom(response(400, { code: "invalid_file", message: "Not a Word file." }), "Upload failed");
    } finally {
      window.removeEventListener(PLAN_LIMIT_EVENT, listener);
    }

    expect(heard).toEqual(["Your plan allows 25 documents."]);
  });

  it("read as a sentence for people", () => {
    expect(errorMessage(new Error("Nope."))).toBe("Nope.");
    expect(errorMessage("not an error", "Something went wrong.")).toBe("Something went wrong.");
  });
});

describe("apiFetch", () => {
  it("sends the session cookie", async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, {}));
    vi.stubGlobal("fetch", fetch);

    await apiFetch("/api/documents");

    expect(fetch).toHaveBeenCalledWith(expect.stringMatching(/\/api\/documents$/), expect.objectContaining({ credentials: "include" }));
  });

  it("turns no answer at all into a NetworkError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiFetch("/api/documents")).rejects.toBeInstanceOf(NetworkError);
  });

  it("sends a signed-out user to the sign-in page and back", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(401, { code: "not_signed_in", message: "Not signed in" })));
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, pathname: "/documents", search: "?q=x", assign });

    await expect(apiFetch("/api/documents")).rejects.toBeInstanceOf(UnauthorizedError);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fdocuments%3Fq%3Dx");
  });
});

it("sends the revision a change was based on as If-Match", () => {
  expect(jsonInit("PUT", { a: 1 }, 7)).toEqual({ method: "PUT", headers: { "Content-Type": "application/json", "If-Match": "7" }, body: '{"a":1}' });
  expect(jsonInit("POST", {}).headers).toEqual({ "Content-Type": "application/json" });
});
