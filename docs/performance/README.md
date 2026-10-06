# Performance

## Benchmarks (PERF-002)

`backend/scripts/benchmark.py` times and measures the memory of the heavy paths, so a performance change can be
shown to help (or to hurt) with numbers from the same script on the same machine. It is not part of the test run;
`backend/tests/test_benchmark_script.py` only checks that it still runs on a tiny case (a few seconds).

```
cd backend
python -m scripts.benchmark                       # everything: about 10 minutes, writes the two files below
python -m scripts.benchmark --quick               # 500 blocks, a 50x8 table, 10 pictures, one repeat: about a minute
python -m scripts.benchmark --only save,load      # a part: import, export, save, patch, load
python -m scripts.benchmark --only save,patch --blocks 1651,12201   # other block counts (PERF-008); --gc-threshold N as the server sets it
python -m scripts.benchmark --timeout 900         # seconds one case may take before it is killed and reported (default 600)
python -m scripts.benchmark --out-dir /tmp/bench  # to compare a run without overwriting the committed one
```

It writes `docs/performance/benchmarks.md` (for people: the machine, then a table per path) and
`docs/performance/benchmarks.json` (the same numbers, each repeat included, for a script to diff).

What it measures, each case in a child process of its own so a case that never ends is killed at the time limit and
listed under "Not finished" instead of hanging the run:

| Path | Input | How |
|---|---|---|
| Import | every `tests/fixtures/documents/*.docx` and `tests/fixtures/word/*.docx` | `build_document_from_docx`, the upload path's parser, in-process |
| Export | the synthetic documents below | `GET /export/docx` and `/export/pdf` through the API: the load from the database, the stored pictures and the build |
| Save | the synthetic documents below | `PUT /documents/{id}/content` through the API (request body made beforehand, so the client's JSON encoding isn't timed) |
| Load | the synthetic documents below | `GET /documents/{id}` through the API |

Synthetic documents are document-model JSON written in the script (the shape the editor sends), in Bulgarian so the
stored JSON has the characters PERF-006 is about; the pictures are PNGs made with Pillow (random noise, 160x120, sent as the
`data:` URIs the editor pastes, which the save moves into asset storage). `blocks-500`, `blocks-2000`, `blocks-5000`
(a heading in ten blocks, a three-item list in twenty-five, the rest paragraphs with a bold run), `table-500x8` (one table of
500 rows by 8 columns) and `pictures-50`.

The API runs in-process on a temporary SQLite file, the way `tests/conftest.py` builds it (a throwaway user, no AI, no
rate limits, local asset folder). Nothing connects to a real database or service.

Reading the numbers:

- Time is `time.perf_counter` around the call: the best and the median of 3 runs (5 for imports). The best is the least
  disturbed by other work on the machine; a difference under about 20% between two runs is noise.
- Memory is `tracemalloc`'s peak over one more run: Python's allocations only (not lxml's, Pillow's or SQLite's own),
  and not comparable with the process's RSS. A run slower than 20 s is timed once and its memory is not measured.
- The first save of a document, which stores its pictures and builds its first version, is not timed; the timed saves
  rewrite the same content (the common autosave).
- Compare runs only from the same machine; the file names it, with the git commit it ran on.
- `benchmarks.md` / `.json` in this folder are the baseline, measured on commit 370ed49 (before PERF-006). The run
  after PERF-006 (save and load only, which is all it touches) is in `after-perf-006/`, the run after PERF-001 (export
  only) in `after-perf-001/`. Re-run and commit the files again when a change is meant to move these numbers; never
  compare them with a run from another machine (the PERF-001 run's CPU reports 2.10 GHz, the baseline's 2.80 GHz:
  the same class of shared container, not the same machine).
- The Word export of a 500x8 table took 247 s in the baseline (PERF-001), so that case is what makes a full
  benchmark take about 10 minutes; its memory was not measured (a run over 20 s is timed once). `--only` or `--quick`
  leave it out, `--timeout` bounds it.

## UTF-8 JSON storage (PERF-006)

Document JSON is stored as UTF-8: the letters as they are, not as `\uXXXX` escapes. SQLAlchemy's default JSON
serializer is `json.dumps` with `ensure_ascii=True`, which writes every Cyrillic letter as six ASCII bytes
(`Д`) where UTF-8 takes two. Now every engine is made by `make_engine` (`app/db/session.py`) with
`json_serializer=dump_json` (`app/db/types.py`): the same `json.dumps` (separators, key order, NaN) with
`ensure_ascii=False`, and the escaped form only for a text holding an unpaired surrogate, which UTF-8 can't write.
The tests' engines and the benchmark's go through `make_engine` too, so what they store is what production stores.

Where the bytes change, precisely:

- Every JSON column (`documents.data`, `document_versions.data`, `processing_jobs.payload` and `result`, the
  templates' rules, ...) uses `JSONVariant`: `JSON` on SQLite, `JSONB` on Postgres. No column is `Text`.
- SQLite (the tests, the end-to-end server, a local run) stores JSON as text, so the rows really shrink.
- Postgres `jsonb` stores a parsed binary form, which holds the letters either way, and prints them unescaped. So
  what Postgres keeps on disk does not change; what shrinks is the text the app sends to the database. This was not
  measured on Postgres: no real database is used here.
- Reading: `json.loads` takes both forms, so rows written before stay readable (a test writes one by raw SQL and reads
  it through the model and the API) and are rewritten as letters the next time they are saved. Nothing is migrated.
- Responses already went out as UTF-8 (FastAPI writes JSON with the letters, no escapes, and `application/json` has no
  charset parameter because JSON is UTF-8 by definition); a test now says so.
- `usage_service.storage_bytes` summed `length(cast(data as text))`, which counts characters, not bytes. Since PLAN-005
  it sums the bytes (`octet_length`, the same on both databases: `app/db/types.py`), so a Cyrillic letter counts two.

Size of the stored `documents.data` in bytes ("before" is the same row written with escapes):

| Document | Before | After | Smaller |
|---|---:|---:|---:|
| 500 Bulgarian blocks (`blocks-500`) | 1,117,596 | 564,084 | 49.5% |
| 2000 blocks | 4,463,490 | 2,248,418 | 49.6% |
| 5000 blocks | 11,154,890 | 5,617,738 | 49.6% |
| table 500x8, short Cyrillic cells | 1,408,015 | 1,199,423 | 14.8% |
| 50 pictures (captions only) | 111,055 | 77,743 | 30.0% |
| `12-complex.docx` imported | 49,582 | 49,072 | 1.0% |
| `r01-university-paper.docx` (Word fixture, 2,287 Cyrillic letters) | 79,160 | 69,984 | 11.6% |

A document's JSON holds a lot of ASCII besides its text (resolved styles, field names, ids), so the saving follows how
much of the document is Cyrillic text: about half for prose, 1% for a fixture with a few Cyrillic words.
`document_versions` rows shrink the same way, and a document has up to one per undo step.

Cost: serializing a 4 MB document takes about 8 ms more (25 to 33 ms, with the surrogate check), and the sqlite3
driver, given a text that is not pure ASCII, makes a UTF-8 copy of it while binding, so the Python heap peak of a save
grew by about 20% (500 blocks: 6.9 to 8.3 MiB; 5000 blocks: 68.8 to 81.5 MiB). The times of save and load did not move
beyond the noise of the machine; the numbers are in `after-perf-006/benchmarks.md`.

## Table export (PERF-001)

The Word export of a table now grows with its number of cells. It used to grow with the square of its rows: a
500 x 8 table took minutes, because python-docx's `table.cell()` rebuilds the whole layout grid on every call and
`cell.merge()` walks every row to find a cell's row and the one below it.

What the export does now (`_add_table` and `_merge_cells` in `backend/app/export/docx_export.py`):

- the table's cells are taken once, from its rows as they are made, and merged cells are merged with python-docx's
  own steps applied to those cells (same XML, no lookups);
- the cell paragraph style ("Table Text") is looked up once per table, not once per cell or paragraph (the lookup
  scans every style).

Measured on a 4-core machine shared with other jobs (the import not counted): 500 x 8 in 0.8 s (231 s before),
1000 x 8 in 1.5 to 1.9 s (1017 s before). The exported XML is unchanged; the figures are in
`docs/cloud-reports/PERF-001.md`. Through the whole download path (`python -m scripts.benchmark --only export`,
database read and pictures included, on a shared 4-core container), the 500 x 8 table's Word export took 706 ms
(best of 3) against 247 s in the baseline, its memory 11.8 MiB; the other exports did not move beyond the noise
(`after-perf-001/benchmarks.md`).

Check it:

- `cd backend && python -m scripts.benchmark_table_export` prints the time for 250, 500 and 1000 rows of 8 columns
  and runs the package check on each result (`--into-original` exports into the imported file, `--profile` prints
  the most expensive functions, `--rows` and `--columns` change the sizes).
- `backend/tests/test_export_scaling.py` runs in a few seconds: the time at four times the rows must stay well
  under the square's (a ratio, so a slow machine passes), the export must not use `table.cell()`, `cell.merge()` or
  the whole-table lookups behind them, merging must equal python-docx's, and the table that comes out must be the
  one made cell by cell.

Not covered here (done in PERF-008, next section): a cell's paragraphs other than plain ones (headings, lists,
quotes inside a cell) looked their style up per paragraph, about 2 ms each.

What was measured, what was changed for it, and the numbers. One section per task.

## Cost of a save, and the export's style lookups (PERF-008)

**A save** (`PATCH` and `PUT /documents/{id}/content`, `services/document_service.py`) loaded the stored document whole,
validated it, dumped it four times (before, the row, the undo step, the answer), encoded it twice and compressed it, all on
the event loop. Profile at 1,651 and 12,201 blocks (cProfile and timers on a shared 4-core container): the dumps, the
validation and the JSON in and out were the bulk, and at 12,201 blocks a third of the time was the garbage collector's
full passes through the millions of small objects a save builds (pauses of 0.25 to 0.4 s).

What changed, with the output unchanged (`tests/test_save_path_unchanged.py` holds the stored row, every version record and
every answer of a fixed sequence of edits to hashes recorded by the code before the change):

- the document is dumped twice instead of four times; that one dump is the row, the undo step and the answer
  (`EncodedJSON`: the dict with its stored text, so the flush does no `json.dumps`), and it cannot be changed after;
- reading (the row's JSON comes as text through `CAST`, decoded, validated, styles resolved), dumping, the patch's answer
  and the packing of the undo step (JSON and zlib) run in `asyncio.to_thread` on plain data, never on the session or a row;
  `json.dumps` is done a few hundred elements at a time, because one call keeps the interpreter's lock to its end;
- `needs_base` asks with `EXISTS` instead of reading the step's state, and `content_delta` compares an unchanged element
  in one comparison;
- `GC_GEN0_THRESHOLD` (default 50,000, set at server start; 0 leaves Python's 2,000): see below.

Measured with `python -m scripts.benchmark --only save,patch --blocks 1651,12201` (best of 4; wall time / CPU time of the
best run; a shared container, so wall times move by 20% or more; `before-perf-008/`, `after-perf-008/`,
`after-perf-008/with-gc-threshold/`):

| | before | after | after + `GC_GEN0_THRESHOLD` |
|---|---:|---:|---:|
| PATCH, 1,651 blocks | 229 ms / 181 ms | 159 ms / 149 ms | 167 ms / 133 ms |
| PATCH, 12,201 blocks | 1.56 s / 1.55 s | 1.36 s / 1.24 s | 0.96 s / 0.91 s |
| PUT, 1,651 blocks | 228 ms / 213 ms | 201 ms / 190 ms | 201 ms / 179 ms |
| PUT, 12,201 blocks | 1.86 s / 1.80 s | 1.76 s / 1.71 s | 1.11 s / 1.09 s |

The PUT's own cost is mostly FastAPI parsing a 10 MB body and writing the answer, which this task did not touch.

The event loop: the longest wait of a ticker task during a PATCH of a 10,000-block document was 0.2 to 0.5 s (a quarter to
a half of the save) and is now 0.05 to 0.1 s (5 to 10%). Left: `json.loads` of the row (about 0.1 s at 12,201 blocks, one
C call) and the collector's passes when `GC_GEN0_THRESHOLD` is 0. Pydantic's dump and validate call back into Python often
enough that the loop gets its turn inside them (measured), so they are not cut into pieces; `json.dumps` and the regex scan
for lone surrogates are. `tests/test_save_responsiveness.py` asserts it as a ratio (best of 5 saves, collector off).

**Export, style lookups.** python-docx's `get_style_id` scans every style of the file (about 2 ms with a Word file's styles;
`default_for` alone walks them all), and the Word export asked once per heading, list item, quote, code block and cell
paragraph. The answers are now remembered per python-docx document and forgotten when the styles part gains a child (the
export adds Word's own styles as their kind of block first comes up); errors are python-docx's and not remembered. The
body paragraph is placed in front of the section properties from the end of the body, not by python-docx's search of all its
children, which made 10,000 paragraphs take 4.3 s (quadratic). 10,000 plain paragraphs: 4.3 s to 1.0 s; 10,000 blocks of
headings, quotes, code and paragraphs: about 10 s to 1.7 s. Every part of 78 exports (the 37 fixtures fresh and into the
original, plus synthetic documents with every block kind in the body, cells and quotes, into originals lacking styles) is
byte for byte what it was, `dcterms:created` and `dcterms:modified` apart. `tests/test_export_styles.py` checks it.
Still quadratic, not part of this: each list looks through the document's numbering (`_new_list_numbering`).

## Version history storage (PERF-004)

Undo steps (`document_versions`, `services/version_history.py`) each hold the whole document state after one change.
They used to be stored as plain JSON (`jsonb` on Postgres), bounded only in number (`DOCUMENT_HISTORY_MAX_STEPS`, 50).

**Compressed.** A step is now stored as zlib (level 6) of compact UTF-8 JSON in `compressed_data` (`bytea`; BLOB on
SQLite). `backend/tests/fixtures/documents/12-complex.docx` as imported: **49,579 bytes of JSON -> 10,021 bytes stored
(4.9x)**; `tests/test_version_history_storage.py` asserts at least 3x. zlib rather than deltas: undo, redo, restore,
viewing and comparing read one row and decompress it (for this document about 0.8 ms to read back, decompression and
JSON parsing together, and 1.4 ms to pack, on the development container), trimming never has to rebase a chain, and the asset sweep can read every row on its own. Postgres's TOAST compression (pglz) was not
enough on its own: it only applies to values over about 2 KB, compresses JSON less than zlib, and nothing outside
Postgres (SQLite in tests, storage metering) sees it. Compressed `bytea` is left uncompressed by TOAST, which gives up
on data that doesn't shrink.

**Bounded in bytes too.** `DOCUMENT_HISTORY_MAX_BYTES` (default 10 MB per document, compressed): past it the oldest
undo steps go, in one cut, so undo never meets a gap. Never trimmed: the original (version 1), the step the document
shows, the one just below it (the last change, a restore included, can always be undone) and any redo steps. Undo and
redo only move the pointer and never trim. With the defaults, an ordinary document is bounded by the 50 steps long
before the bytes (50 steps of 12-complex.docx take about 0.5 MB).

**Pictures are references.** A step holds an image as its asset id, never its bytes. A document that still holds
inline `data:` pictures (saved before pictures, or nested ones, moved into storage) has them moved into assets before
its step, or its base step, is recorded. The unused-asset sweep decompresses every version when looking for the assets
still referred to, so a picture only an undo step shows is kept.

**Older rows.** Rows written before (`data`, uncompressed) are read as they are and are not rewritten: migration
`b8534d3c4256` is schema-only (quick, and renders in offline `--sql` mode). They age out under the same rule; a check
constraint makes each row hold exactly one of the two copies. Its downgrade decompresses every compressed row back
into `data` before dropping the column.

**Metering.** A workspace's storage (`usage_service.storage_bytes`: `GET /usage`, billing, the plan's storage limit)
now counts its versions as stored: the compressed bytes, or an older row's JSON text.
