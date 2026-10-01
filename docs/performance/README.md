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
- `benchmarks.md` in the repository is the baseline made on the commit before PERF-006, and the run after it, see
  below. Re-run and commit the files again when a change is meant to move these numbers.
