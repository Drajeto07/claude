import { afterEach, describe, expect, it, vi } from "vitest";

import { importFile, waitForJob, WHOLE_UPLOAD_MAX_BYTES } from "./jobs";
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

async function uploadedForm(options?: { autolink?: boolean; pdfMode?: "editable" | "layout" }, name = "report.docx"): Promise<FormData> {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response({ id: "job-1", status: "succeeded", stage: "done", progress: 100, result: { documentId: "doc-1" } }))
    .mockResolvedValueOnce(response({ id: "doc-1", elements: [] }));
  vi.stubGlobal("fetch", fetch);

  await importFile(new File(["x"], name), undefined, undefined, options);

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

describe("importing a PDF", () => {
  it("asks for an editable document unless the person chose the layout (P2E-007)", async () => {
    expect((await uploadedForm(undefined, "report.pdf")).has("pdf_mode")).toBe(false);
    expect((await uploadedForm({ pdfMode: "editable" }, "report.pdf")).has("pdf_mode")).toBe(false);
    expect((await uploadedForm({ pdfMode: "layout" }, "report.pdf")).get("pdf_mode")).toBe("layout");
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

// -- A large file in parts (B-035A) --------------------------------------------------------------------------------

const MiB = 1024 * 1024;
const UPLOAD = { uploadId: "0b6c6f5e-0000-4000-8000-000000000001", chunkSize: 3 * MiB, chunks: 2, expiresAt: "2026-10-23T12:00:00Z" };
const DONE = { id: "job-9", status: "succeeded", stage: "done", progress: 100, result: { documentId: "doc-9" } };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function sha256(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function bigFile(size = 5 * MiB): File {
  const bytes = new Uint8Array(size);
  for (let index = 0; index < size; index += 4096) bytes[index] = index % 251;
  return new File([bytes], "report.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
}

/** The server: start, the parts, completion, then the new document. `partFails`: how many times each part's first tries fail. */
function server({ partFails = 0, partStatus }: { partFails?: number; partStatus?: number } = {}) {
  const failed = new Map<string, number>();
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/jobs/import-file")) return json(DONE, 202);
    if (url.endsWith("/jobs/import-file/uploads")) return json(UPLOAD, 201);
    if (url.includes("/parts/")) {
      url = url.split("?")[0];
      const seen = failed.get(url) ?? 0;
      if (seen < partFails) {
        failed.set(url, seen + 1);
        throw new TypeError("Failed to fetch");
      }
      if (partStatus) return json({ code: "upload_incomplete", message: "Gone." }, partStatus);
      return json({ index: Number(url.split("/").pop()), size: (init.body as Blob).size });
    }
    if (url.endsWith("/complete")) return json(DONE, 202);
    return json({ id: "doc-9", elements: [] });
  });
}

describe("importing a large file (B-035A)", () => {
  it("a file up to 3 MiB still goes whole, in one request", async () => {
    const fetch = server();
    vi.stubGlobal("fetch", fetch);
    await importFile(new File([new Uint8Array(WHOLE_UPLOAD_MAX_BYTES)], "small.docx"));
    expect(fetch.mock.calls[0][0]).toMatch(/\/jobs\/import-file$/);
  });

  it("a larger file goes in parts of the size the server gives, each with its SHA-256, then is completed once", async () => {
    const fetch = server();
    vi.stubGlobal("fetch", fetch);
    const file = bigFile();
    const progress: number[] = [];
    const document = await importFile(file, "Big report", (step) => step.stage === "uploading" && progress.push(step.progress), { autolink: true });
    expect(document.id).toBe("doc-9");

    const [startUrl, startInit] = fetch.mock.calls[0];
    expect(startUrl).toMatch(/\/jobs\/import-file\/uploads$/);
    expect(JSON.parse(startInit!.body as string)).toEqual({
      filename: "report.docx",
      size: file.size,
      sha256: await sha256(file),
      contentType: file.type,
      title: "Big report",
      autolink: true,
      pdfMode: "editable",
    });
    const parts = fetch.mock.calls.filter(([url]) => String(url).includes("/parts/"));
    expect(parts.map(([url]) => new URL(String(url), "https://x").pathname.split("/").pop())).toEqual(["0", "1"]);
    expect(parts.map(([, init]) => (init!.body as Blob).size)).toEqual([3 * MiB, 2 * MiB]);
    for (const [index, [url, init]] of parts.entries()) {
      expect(new URL(String(url), "https://x").searchParams.get("sha256")).toBe(await sha256(file.slice(index * 3 * MiB, (index + 1) * 3 * MiB)));
      // Only a header the API's CORS policy allows.
      expect(Object.keys(init!.headers as Record<string, string>)).toEqual(["Content-Type"]);
    }
    const completes = fetch.mock.calls.filter(([url]) => String(url).endsWith("/complete"));
    expect(completes).toHaveLength(1);
    expect(completes[0][1]!.headers).toBeUndefined();
    expect(progress).toEqual([0, 50, 100]);
  });

  it("a part that didn't get through is sent again", async () => {
    const fetch = server({ partFails: 1 });
    vi.stubGlobal("fetch", fetch);
    expect((await importFile(bigFile())).id).toBe("doc-9");
    expect(fetch.mock.calls.filter(([url]) => String(url).includes("/parts/0?"))).toHaveLength(2);
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/complete"))).toHaveLength(1);
  });

  it("an upload that keeps failing says it was interrupted -- never that it worked", async () => {
    const fetch = server({ partFails: 99 });
    vi.stubGlobal("fetch", fetch);
    await expect(importFile(bigFile())).rejects.toMatchObject({ code: "upload_interrupted" });
    expect(fetch.mock.calls.filter(([url]) => String(url).includes("/parts/0?"))).toHaveLength(4); // the first try and three more
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("/complete"))).toHaveLength(0);
  }, 15_000);

  it("a refusal from the server isn't retried: it says why", async () => {
    const fetch = server({ partStatus: 409 });
    vi.stubGlobal("fetch", fetch);
    await expect(importFile(bigFile())).rejects.toMatchObject({ code: "upload_incomplete", status: 409 });
    expect(fetch.mock.calls.filter(([url]) => String(url).includes("/parts/"))).toHaveLength(1);
  });
});
