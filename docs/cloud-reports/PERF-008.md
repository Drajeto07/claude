# PERF-008: cheaper saves off the event loop, cached export style lookups

Branch `cloud/perf-008-save-cost`, from `feature/smartdoc-production-hardening` at 8966ec7, merged (merge commit) with 7ba8c0c
(PLAN-001..005, PDF-010..012, ACCT-005..007, SEC-020/STOR-001). Commit prefix `cloud PERF-008`.

## Summary

**Part 1, a save.** After PERF-003 a save travels as a patch, but the server loaded and validated the stored document whole,
dumped it four times, encoded and compressed it, all on the event loop. Now: two dumps instead of four, shared by the row,
the undo step and the answer; reading, dumping, the patch's answer and packing the undo step (JSON, zlib) run in
`asyncio.to_thread` on plain data; `json.dumps` and the surrogate scan in pieces so the loop gets the interpreter's lock;
a GC threshold setting. What is stored and answered is byte for byte unchanged (golden test, recorded by the code before).

**Part 2, export.** python-docx's `get_style_id` scans every style (about 2 ms) and the export asked once per heading,
list item, quote, code block and cell paragraph. Remembered per python-docx document, forgotten when styles are added. Also
found and fixed: the body paragraph placement was quadratic (10,000 paragraphs: 4.3 s, now 1.0 s). All 78 exports byte-identical.

## Profile (shared 4-core container, load 4 to 12, so times move by 20% or more)

PATCH one paragraph, 1,651 blocks: about 170 ms. 12,201 blocks: about 1.4 s. Stages at 12,201 (collector off): read and
validate 240 ms, dumps 3 x 45, `holds_inline_images(before)` 50-65, `json.dumps` for the row 90, `pack_snapshot` (JSON 90 +
zlib 80-140), flush 180, `content_delta` 70. The owner's "model_dump x4 0.47 s" was mostly the collector: with the default
threshold one full pass (0.15 to 0.4 s) landed inside a dump every save; each dump alone is 6-9 ms at 1,651 and 40 ms at 12,201.
With the collector off the same save took 1.0 s instead of 1.4 s. Threads do not help a single long C call: `json.dumps` of the
12k document blocked the loop 86 ms, `json.loads` 92-100 ms, a regex scan of 10 MB 43-100 ms; pydantic's dump and validate
only 12-48 ms because they call back into Python.

## Files changed

- `backend/app/services/document_service.py` (`_load_for_write`, `_save` new, `_write`, `_change`, `patch_content`, `_take_elements` split into `_adopt`/`_settle`), `version_history.py` (packing in a thread, `needs_base` as EXISTS), `content_patch.py` (`content_delta`)
- `backend/app/repositories/document_repository.py` (`stored_form`, `document_from_json`, `get_row_with_json_for_user`, `apply(data=)`), `app/db/types.py` (`EncodedJSON`, `dumps_in_pieces`), `app/db/models/document.py` (`pack_snapshot`)
- `backend/app/config.py`, `app/main.py`, `.env.example` (`GC_GEN0_THRESHOLD`)
- `backend/app/export/docx_export.py` (`_StyleLookups`, `_style_id`, `_new_paragraph`, `_add_paragraph_at_end`, `_named_style`, `_table_style`, `_add_table`)
- `backend/scripts/benchmark.py` (`--blocks`, `--gc-threshold`, PATCH case, CPU time column)
- tests: `test_save_path_unchanged.py`, `test_save_cost.py`, `test_save_responsiveness.py`, `test_export_styles.py`, fixture `fixtures/save_path_golden.json`
- docs: `docs/performance/README.md` (section PERF-008), `docs/performance/before-perf-008/`, `after-perf-008/`, `after-perf-008/with-gc-threshold/`, this report

No API schema, importer output or migration changed (no OpenAPI/types regeneration; migrations: none).

## Design decisions

- **One dump shared** (`stored_form` -> `EncodedJSON`): the dict plus the text `dump_json` makes of it, made in a thread after the
  document's last change. Row, version and answer all use it; mutating its top level raises. A dict reused after mutation would
  be a bug, so the golden test compares every step, and `test_the_row_and_the_newest_version_are_both_a_fresh_dump...` compares
  with a fresh dump after each save.
- **Threads get plain data only**: text, dicts, the pydantic model (never shared across awaits), never a session, row or
  version. `test_the_work_on_the_document_runs_in_threads_on_plain_data` records what goes to `to_thread` and fails on an
  ORM/session argument.
- **Row JSON read as text** with `CAST(data AS TEXT)` and `defer(data)` so decoding is in the thread (on Postgres the asyncpg
  codec would decode on the loop, and `type_coerce` does not avoid it). The row's `data` stays unloaded; a write sets it.
- **Pieces only where measured**: `json.dumps` (86 ms single call to 22 ms longest wait) and the surrogate scan. Slicing the
  pydantic dump/validate gave no gain and was removed.
- **`GC_GEN0_THRESHOLD=50000`** (setting, applied at server start, 0 = Python's default): the biggest single win at 12k
  (PATCH 1.56 s to 0.96 s). A process-wide behaviour, so it is an owner decision.
- **Style cache** keyed on python-docx's part, token = (child count of the styles part, its last child); a positive or negative
  answer is reused only while the token is unchanged. It calls python-docx's own `get_style_id` on a miss, so values and errors
  are python-docx's.
- **Not done on purpose**: PUT's answer is still FastAPI's (serialising it elsewhere risks different bytes); an in-memory cache of
  the last saved model per document (memory, multi-worker).

## Tests added

- `test_save_path_unchanged.py` (3): golden sequence of 16 steps (patch, merged autosave, whole save, picture, rename, add page,
  undo/redo, restore, two pre-history documents incl. an inline picture) hashes of row, versions, answers; fresh-dump equality
  after each save; dump count == 2 for patch, put, rename.
- `test_save_cost.py` (81 incl. 1 PostgreSQL-marked, skipped locally): JSON in pieces == `json.dumps` (options, sizes, odd values,
  surrogates), no call over a piece, `pack_snapshot` bytes, `EncodedJSON`, every fixture stored/read back, `content_delta` vs the old
  formula (60 random cases), row read as text and patch saved (SQLite; Postgres in CI), GC setting at lifespan and 0.
- `test_save_responsiveness.py` (2): ticker ratio on a 10,000-block PATCH (best of 5 < 0.12; code before: 0.24-0.29, now 0.05-0.08);
  the thread/plain-data test.
- `test_export_styles.py` (10): cached ids equal python-docx's incl. errors, styles added after a lookup, fresh-vs-cached export
  bytes, no scanning lookups growing with size, 10,000-block timing as ratios (vs one style scan and vs 1,000 blocks), placement.

## Results

Full backend suite after the merge: 2233 passed, 11 skipped, 2 warnings (452 s). Byte compare of exports (`snap2.py`, scratch): base 7ba8c0c vs
branch, 37 fixtures fresh + into original + 4 synthetic (every block kind in body/cells/quotes, originals lacking Quote, List
Bullet, headings, Table Grid, Code, Hyperlink): 78 exports, 1,422 parts, 1,422 identical (core.xml `created`/`modified`
normalised; `created` equals the export time for a fresh export). Before the merge: same result against 8966ec7.

Benchmarks: see the README section; PATCH 12,201 blocks 1.56 s -> 1.36 s (CPU 1.55 -> 1.24) -> 0.96 s with the GC setting;
1,651 blocks 229 -> 159 ms. PUT only gains from the GC setting (1.86 -> 1.11 s).

## Mutation checks

| Mutation | Result |
|---|---|
| model loaded in the loop (no `to_thread`) | loop test and thread test fail |
| `stored_form` in the loop | thread test fails (loop ratio alone did not at 6,000 blocks; 10,000 blocks: 0.19-0.25 > 0.12) |
| row written from a changed copy of the dump | 3 fail |
| `content_delta` fast path drops the order-free compare | 3 fail |
| GC threshold not applied | 1 fails |
| `EncodedJSON` mutable | 1 fails |
| `needs_base` EXISTS off by one | 14 fail |
| `_PIECE` huge (no pieces) | piece test fails |
| style cache always misses | 2 fail (scan count, timing) |
| style cache never invalidated | 2 fail |
| body search as python-docx | timing fails |
| the loop test on the code before the change | fails (0.24-0.29 > 0.12) |

## Commands run

`pytest` on the files above; `python -m scripts.benchmark --only save,patch --blocks 1651,12201 --repeats 4 [--gc-threshold 50000]`
(before = a `git archive` of the base with this script; 2 passes, pass 2 committed); cProfile/stage-timer scripts (scratch);
`snap2.py`/`compare2.py` (scratch); full suite.

## Risks and open questions

- Postgres not run here (no database was assigned): `CAST(jsonb AS TEXT)` + `defer` is exercised by the PostgreSQL-marked test in
  `test_save_cost.py`, which CI's postgres job runs. Writes still send text as before.
- A cancelled request leaves a thread finishing a pure computation on its own copy; nothing shared.
- `GC_GEN0_THRESHOLD`: raises memory held by short-lived garbage slightly; owner to confirm the default.
- Style cache assumes nothing changes an existing style's name/default flag mid-export (the export only adds).
- A document still held in memory 3 times during a save (model, before dict, after dict): peak heap +- same as before
  (benchmark 164 MiB at 12,201 either way).

## Not done / follow-ups

- `json.loads` of the row (0.1 s at 12k) and PUT's request parsing/answer are still one call each on the loop.
- `_new_list_numbering` scans all `w:num` per list (quadratic in the number of lists); python-docx's `add_table` placement likewise.
- The other `-> Document` routes (format, undo, ...) serialise on the loop as before.
