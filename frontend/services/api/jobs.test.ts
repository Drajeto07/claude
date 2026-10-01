import { afterEach, describe, expect, it, vi } from "vitest";

import { importFile, waitForJob } from "./jobs";
import type { Job } from "@/types/document";

/**
 * A Word upload leaves plain-text addresses as text unless the person asks for
 * links (tracker DOCX-026): the form says so only then.
 */

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

async function uploadedForm(options?: { autolink?: boolean }): Promise<FormData> {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response({ id: "job-1", status: "succeeded", stage: "done", progress: 100, result: { documentId: "doc-1" } }))
    .mockResolvedValueOnce(response({ id: "doc-1", elements: [] }));
  vi.stubGlobal("fetch", fetch);

  await importFile(new File(["x"], "report.docx"), undefined, undefined, options);

  const [path, init] = fetch.mock.calls[0];
  expect(path).toMatch(/\/jobs\/import-file$/);
  return init.body as FormData;
}

describe("importing a Word file", () => {
  it("keeps plain-text addresses as text unless asked", async () => {
    expect((await uploadedForm()).has("autolink")).toBe(false);
  });

  it("asks for links when the person wants them", async () => {
    expect((await uploadedForm({ autolink: true })).get("autolink")).toBe("true");
  });
});

describe("waiting for a job", () => {
  it("stops polling a job that was cancelled, with a reason", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const cancelled = { id: "job-1", status: "cancelled", stage: "cancelled", progress: 10 } as Job;

    await expect(waitForJob(cancelled)).rejects.toMatchObject({ code: "job_cancelled", message: "This was cancelled." });
    expect(fetch).not.toHaveBeenCalled();
  });
});
