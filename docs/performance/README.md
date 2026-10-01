# Performance

## Benchmarks (PERF-002)

`backend/scripts/benchmark.py` times and measures the memory of the heavy paths, so a performance change can be
shown to help (or to hurt) with numbers from the same script on the same machine. It is not part of the test run;
`backend/tests/test_benchmark_script.py` only checks that it still runs on a tiny case (a few seconds).

```
cd backend
python -m scripts.benchmark                       # everything: about 10 minutes, writes the two files below
python -m scripts.benchmark --quick               # 500 blocks, a 50x8 table, 10 pictures, one repeat: about a minute
python -m scripts.benchmark --only save,load      # a part: import, export, save, load
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
  after PERF-006 (save and load only, which is all it touches) is in `after-perf-006/`. Re-run and commit the files
  again when a change is meant to move these numbers; never compare them with a run from another machine.
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
- `usage_service.storage_bytes` sums `length(cast(data as text))`, which counts characters, not bytes: on SQLite a
  Cyrillic document now counts about what it already counted on Postgres.

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
