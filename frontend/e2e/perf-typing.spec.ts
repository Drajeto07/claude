import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, editor, signUp, waitUntilSaved } from "./helpers";

/**
 * Typing in a long document (tracker PERF-005): how long a keystroke takes to show at 5,000
 * and 12,000 blocks, in the real editor of a production build. Not part of the usual run --
 * PERF_TYPING=1 npx playwright test e2e/perf-typing.spec.ts -- since a 12,000-block document
 * takes a while to open. Each keystroke's latency is from its keydown to the frame after it
 * (requestAnimationFrame, then a task: past the paint), so everything the editor does in
 * step with a keystroke counts; long tasks after typing (autosave's work) are listed too.
 * Writes PERF_TYPING_OUT (default: the temp folder) as JSON, and prints a summary.
 */

test.skip(!process.env.PERF_TYPING, "PERF_TYPING=1 to measure typing in long documents");
test.setTimeout(600_000);

const backend = path.resolve(__dirname, "..", "..", "backend");
const python = process.platform === "win32" ? path.join(backend, "venv", "Scripts", "python.exe") : path.join(backend, "venv", "bin", "python");
const SIZES = (process.env.PERF_TYPING_SIZES ?? "5000,12000").split(",").map(Number);
const TYPED = "the quick brown fox jumps over the lazy dog ";

/** The benchmark's synthetic document (scripts/benchmark.py): a heading in ten, a list in twenty-five. */
function blocks(count: number): unknown[] {
  const out = execFileSync(python, ["-c", `import json,sys; from scripts.benchmark import blocks_document; sys.stdout.write(json.dumps(blocks_document(${count}), ensure_ascii=False))`], {
    cwd: backend,
    maxBuffer: 256 * 1024 * 1024,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  return JSON.parse(out.toString("utf-8"));
}

type CpuProfile = {
  nodes: { id: number; callFrame: { functionName: string; url: string; lineNumber: number }; children?: number[] }[];
  samples: number[];
  timeDeltas: number[];
};

/** The functions most time was spent in (self time), and with what they call (total), while typing. */
function printHotSpots(profile: CpuProfile) {
  const byId = new Map(profile.nodes.map((node) => [node.id, node]));
  const parent = new Map<number, number>();
  for (const node of profile.nodes) for (const child of node.children ?? []) parent.set(child, node.id);
  const self = new Map<string, number>();
  const total = new Map<string, number>();
  profile.samples.forEach((id, index) => {
    const delta = (profile.timeDeltas[index] ?? 0) / 1000;
    const name = (node: CpuProfile["nodes"][number]) =>
      `${node.callFrame.functionName || "(anonymous)"} ${node.callFrame.url.split("/").pop()}:${node.callFrame.lineNumber}`;
    const node = byId.get(id)!;
    self.set(name(node), (self.get(name(node)) ?? 0) + delta);
    const seen = new Set<string>();
    for (let at: number | undefined = id; at !== undefined; at = parent.get(at)) {
      const key = name(byId.get(at)!);
      if (!seen.has(key)) total.set(key, (total.get(key) ?? 0) + delta);
      seen.add(key);
    }
  });
  const top = (map: Map<string, number>) => [...map].sort((a, b) => b[1] - a[1]).slice(0, Number(process.env.PERF_TYPING_TOP ?? 25)).map(([key, ms]) => `  ${ms.toFixed(0).padStart(6)} ms  ${key}`);
  console.log(["self time:", ...top(self), "total time:", ...top(total)].join("\n"));
}

function percentile(values: number[], p: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))] ?? NaN;
}

async function measureTyping(page: Page, where: "start" | "middle") {
  await page.evaluate(() => {
    const w = window as unknown as { __latencies: number[]; __longTasks: number[]; __measuring?: boolean };
    w.__latencies = [];
    w.__longTasks = [];
    if (w.__measuring) return; // listening already: the counts start again
    w.__measuring = true;
    document.addEventListener(
      "keydown",
      (event) => {
        const start = event.timeStamp;
        requestAnimationFrame(() => setTimeout(() => w.__latencies.push(performance.now() - start), 0));
      },
      true,
    );
    new PerformanceObserver((list) => list.getEntries().forEach((entry) => w.__longTasks.push(entry.duration))).observe({ type: "longtask" });
  });
  const paragraphs = editor(page).locator("p");
  const count = await paragraphs.count();
  const target = paragraphs.nth(where === "start" ? 1 : Math.floor(count / 2));
  await target.scrollIntoViewIfNeeded();
  await target.click();
  await page.keyboard.press("End");
  await page.waitForTimeout(500);
  const profiler = process.env.PERF_TYPING_PROFILE ? await page.context().newCDPSession(page) : null;
  if (profiler) {
    await profiler.send("Profiler.enable");
    await profiler.send("Profiler.setSamplingInterval", { interval: 200 });
    await profiler.send("Profiler.start");
  }
  const tracing = process.env.PERF_TYPING_TRACE ? await page.context().newCDPSession(page) : null;
  const events: { name: string; dur?: number; ph: string }[] = [];
  if (tracing) {
    tracing.on("Tracing.dataCollected", ({ value }) => events.push(...(value as unknown as typeof events)));
    await tracing.send("Tracing.start", { categories: "devtools.timeline,blink,v8.execute", transferMode: "ReportEvents" });
  }
  await page.keyboard.type(TYPED, { delay: 120 });
  if (tracing) {
    const done = new Promise((resolve) => tracing.once("Tracing.tracingComplete", resolve));
    await tracing.send("Tracing.end");
    await done;
    const totals = new Map<string, number>();
    for (const event of events) if (event.ph === "X" && event.dur) totals.set(event.name, (totals.get(event.name) ?? 0) + event.dur / 1000);
    console.log(["trace (ms, summed, nested events overlap):", ...[...totals].sort((a, b) => b[1] - a[1]).slice(0, 30).map(([name, ms]) => `  ${ms.toFixed(0).padStart(7)}  ${name}`)].join("\n"));
  }
  if (profiler) {
    const { profile } = await profiler.send("Profiler.stop");
    printHotSpots(profile as unknown as CpuProfile);
  }
  await page.waitForTimeout(4_000); // autosave and whatever else follows typing
  return page.evaluate(() => {
    const w = window as unknown as { __latencies: number[]; __longTasks: number[] };
    return { latencies: w.__latencies, longTasks: w.__longTasks };
  });
}

test("typing latency in long documents", async ({ page }) => {
  await signUp(page);
  const report: Record<string, unknown> = {};
  for (const size of SIZES) {
    const id = await createDocument(page, { text: "A long document." });
    const elements = blocks(size);
    const saved = await page.request.put(`${API}/documents/${id}/content`, { data: { elements } });
    expect(saved.ok(), await saved.text()).toBeTruthy();

    const opening = Date.now();
    await page.goto(`/documents/${id}`);
    await expect(editor(page)).toBeVisible({ timeout: 300_000 });
    await expect(editor(page).locator("h1, h2, h3").first()).toBeVisible({ timeout: 300_000 });
    const openMs = Date.now() - opening;

    const results: Record<string, unknown> = { openMs };
    const experiment = process.env.PERF_TYPING_STYLE; // an experiment: style on the editor's text area, e.g. "display:block"
    if (experiment) await editor(page).evaluate((element, style) => element.setAttribute("style", `${element.getAttribute("style") ?? ""};${style}`), experiment);
    const attribute = process.env.PERF_TYPING_ATTR; // an experiment: an attribute on it, e.g. "spellcheck=false"
    if (attribute) await editor(page).evaluate((element, pair) => element.setAttribute(pair.split("=")[0], pair.split("=")[1] ?? ""), attribute);
    for (const where of ["start", "middle"] as const) {
      const { latencies, longTasks } = await measureTyping(page, where);
      results[where] = {
        keystrokes: latencies.length,
        p50: Math.round(percentile(latencies, 50)),
        p95: Math.round(percentile(latencies, 95)),
        max: Math.round(Math.max(...latencies)),
        longTasks: longTasks.length,
        longestTask: Math.round(Math.max(0, ...longTasks)),
      };
    }
    await waitUntilSaved(page);
    report[`blocks-${size}`] = results;
    console.log(`blocks-${size}: ${JSON.stringify(results)}`);
  }
  const out = process.env.PERF_TYPING_OUT ?? path.join(os.tmpdir(), "smartdoc-perf-typing.json");
  fs.writeFileSync(out, JSON.stringify({ measuredAt: new Date().toISOString(), report }, null, 1));
});
