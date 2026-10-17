# PERF-001: linear Word export of tables

Branch `cloud/perf-001-linear-table-export` (base 370ed49). Commit prefix `phase-05a-linear-table-export`.

## Summary

The Word export of a table grew with the square of its rows. Cause: python-docx's `table.cell(r, c)` rebuilds the
whole layout grid (`Table._cells`: one `_Cell`, `grid_span` and `vMerge` lookup per cell of the table) on every
call, and `cell.merge()` finds a cell's row and the one below it with `tr_lst.index(...)`, which walks every row.
Fixed without changing the output:

- `_add_table` takes the table's `<w:tc>` elements once (`[tr.tc_lst for tr in tbl.tr_lst]`, right after
  `add_table`, when every cell is still its own) and addresses cells by row and column in that list.
- `_merge_cells` does what `CT_Tc.merge()` does for a rectangle of cells not merged before -- the same
  `_span_to_width` steps top to bottom, in the same order, with the same `vMerge` values -- on the cells at hand,
  instead of through the row and cell-below lookups.
- The cell paragraph style ("Table Text") is looked up once per table (`get_style_id` scans every style, about
  2 ms), and its id is put on the paragraph (`paragraph._p.style = id`, which is what python-docx's `style` setter
  does after its lookup). The id is also passed to the paragraphs of a cell with several blocks
  (`_Place.paragraph_style_id`), which cut the 2-paragraph-cell table from 9.5 s to 2.8 s at 500 x 8.

## Files changed

- `backend/app/export/docx_export.py` (`_add_table`, new `_merge_cells`, `_Place.paragraph_style_id`, `_add_paragraph`)
- `backend/tests/test_export_scaling.py` (new)
- `backend/scripts/benchmark_table_export.py` (new)
- `docs/performance/README.md` (new, section "Table export (PERF-001)")
- `docs/cloud-reports/PERF-001.md` (this report)

## Machine

4 cores (`nproc`), Intel Xeon Processor @ 2.80GHz, Python 3.13.14 (/tmp/venv), python-docx 1.2.0. Three other workers
ran on the same machine, so times are noisy.

## Timings (`python -m scripts.benchmark_table_export`; build_docx only, the import of the generated python-docx file not counted)

| Size | Before (base) | After, 3 runs | 
|---|---|---|
| 250 x 8 | 58.5 s | 0.46, 0.56, 0.50 s |
| 500 x 8 | 230.9 s | 0.89, 0.77, 0.79 s |
| 1000 x 8 | 1016.8 s | 1.90, 1.47, 1.74 s |

- 500 x 8 under 10 s: yes (0.8 s). (The owner's figure of 321 s is the same quadratic curve on a slower machine.)
- 1000 x 8 / 500 x 8: 2.13, 1.92, 2.21 (limit 2.5; the base's was 4.40). Into the original (`--into-original`): 0.57,
  1.52, 3.15 s (1000/500 = 2.08).
- A table of 2-paragraph cells (imported Word cells with several blocks), 125/250/500 rows: 0.64, 1.04, 2.78 s.
- A table with merged cells (every row's first two cells joined, a 2 x 2 block in every 4th row), 125/250/500 rows
  after the fix: 0.22, 0.39, 0.69 s; before the merge change 0.72, 1.42, 4.12 s.
- The package check (`app/export/package_check.py`) runs inside the benchmark on each result (it exits on any
  problem), and in `test_a_big_tables_package_is_sound`; it found nothing for 250/500/1000 x 8, fresh and, in the
  test, into the original.

## cProfile, 250 x 8 (top by cumulative time, paths shortened)

Before (108.3 s under the profiler; 58.5 s without):

```
 108.323  docx_export.py:116(build_docx)
 108.206  docx_export.py:2764(_add_table)
 102.069  docx/table.py:85(cell)                        2000 calls
 101.395  docx/table.py:163(_cells)                     2000 calls, tottime 8.8
  69.547  docx/oxml/xmlchemy.py:380(get_child_element)  16,008,492 calls
  40.172  docx/oxml/table.py:472(grid_span)             4,000,000 calls
  37.412  docx/oxml/table.py:541(vMerge)                4,000,000 calls
  14.416  docx/oxml/ns.py:100(qn)                       17,050,509 calls
   8.391  docx/table.py:195(__init__)                   4,000,000 calls   (a _Cell per cell per call)
   5.381  docx/text/paragraph.py:144(style)             2001 calls (style scan, ~2.7 ms each)
```

After (0.93 s under the profiler):

```
   0.927  docx_export.py:118(build_docx)
   0.808  docx_export.py:2784(_add_table)
   0.382  docx/oxml/xmlchemy.py:284(_add_child)         8,137 calls
   0.328  docx/oxml/text/paragraph.py:90(style)         2001 calls
   0.248  docx_export.py:2029(_add_inline_runs)
   0.234  docx/text/paragraph.py:30(add_run)
   0.104  docx_export.py:2713(_put_in)
```

Nothing left grows faster than the number of cells. Style, numbering and id lookups that scan the whole document
per cell: only the style-id scan above (constant per call, linear in cells) was found; `_unique_drawing_ids`,
`_unique_control_ids` and the controls bookkeeping do not show up in the profile.

## XML comparison (unchanged output)

`scratchpad/snap.py` (not committed): for every `.docx` in `backend/tests/fixtures/documents` (17) and
`backend/tests/fixtures/word` (20) it imports the file as an upload does (`build_document_from_docx`, source kept,
`stamp`), exports it fresh (new document) and into its original (`build_docx(document, source=data)`), checks
`package_problems(...) == []`, and saves every part of the zip. Run on the base commit (copy of the tree at 370ed49) and on
this branch, then diffed part by part (`compare.py`).

- 37 fixtures x 2 ways = 74 exports, 1354 parts compared: 1354 identical, 0 different, no part present in only one.
- Only random thing: `docProps/core.xml` has `<dcterms:modified>` (the export time); it is removed before comparing. Two
  runs of the base against each other differ in nothing else, so nothing else needed normalising.
- A second set written for this task, synthetic and built with python-docx (a plain 12 x 5 table; a 10 x 6 table with
  merged cells across, down and both; a table with 2-paragraph cells, a bulleted paragraph, a right-aligned bold
  one, a nested table with its own merge and merged cells around it), fresh and into the original, base against
  branch: 6 exports, 102 parts, all identical. The merges there are where the vMerge/gridSpan code is exercised.
- The fixtures' tables hold few merges, so `test_merging_cells_at_hand_is_what_python_docx_merge_does` compares
  `_merge_cells` with python-docx's own `table.cell().merge()` on 40 random tables of up to 7 x 7 with several
  non-overlapping merged blocks each, comparing the whole `<w:tbl>` element.

## Tests added: `backend/tests/test_export_scaling.py` (6 tests, 6 passed in about 6 s)

- `test_exporting_a_table_grows_with_its_cells_not_their_square`: 200 rows vs 50 rows (4x the cells), best of 2
  runs each, ratio under 9 (linear about 2.6 to 4, the square about 16).
- `test_a_big_table_with_merged_cells_grows_with_its_cells_too`: 800 vs 100 rows of a merged table, ratio under 11
  (fixed: 5 to 7; with python-docx's merge: 12 to 14).
- `test_the_export_never_uses_the_lookups_that_walk_the_whole_table`: `Table.cell`, `Table._cells`, `_Cell.merge`,
  `CT_Tc.merge`, `CT_Tc._tr_idx` and `CT_Tc._tc_below` raise; a plain and a merged table export fine. A
  deterministic guard that doesn't depend on the clock.
- `test_a_big_tables_package_is_sound`: 250 x 8 into its original, and a merged 250-row table, `package_problems == []`.
- `test_a_small_table_comes_out_as_one_made_cell_by_cell`: a 9 x 8 merged table's cells (columns spanned, vertical
  merge, text) equal a table made with python-docx's `table.cell()` and `merge()`.
- `test_merging_cells_at_hand_is_what_python_docx_merge_does`: described above.

Existing suites run on the branch: `tests/test_docx_tables.py`, `test_docx_export.py`, `test_original_blocks.py`,
`test_docx_preservation.py` all pass.

Full backend suite on this branch (after the last code change), run in the background while the other workers also
ran: `1731 passed, 1 skipped, 2 warnings in 332.97s` (base: 1725 passed, 1 skipped, plus the 6 new tests; no
failures, so no baseline differences on this machine).

## Mutation checks (each reverted afterwards)

| Mutation | Result |
|---|---|
| `table.cell(r, c)` per cell again | `test_the_export_never_uses_the_lookups...` fails at once; the timing test fails too (50 rows 2.2 s, 200 rows 35.9 s, ratio 16) |
| `target.merge(...)` of python-docx again (via the grid cells) | `...never_uses_the_lookups...` fails; the merged timing test fails (100 rows 0.60 s, 800 rows 7.25 s, ratio 12) |
| `_merge_cells` writes `vMerge restart` for a 1-row block (`None` expected) | `test_a_small_table_comes_out_as_one_made_cell_by_cell` and `test_merging_cells_at_hand...` fail |
| cell addressed one column to the right (a stale/wrong grid) | `test_a_small_table_comes_out_as_one_made_cell_by_cell` fails |

Not caught by any test, said plainly: putting the per-cell `first.style = "Table Text"` lookup back (and not passing
`paragraph_style_id`) gives the same output and still scales linearly, only about 3x slower for plain cells; it
isn't a scaling bug, so no test pins it.

## Design decisions and why

- Cells are addressed in the grid made before any merge. That is the same cell python-docx's `table.cell()` returns
  because the export only places a cell at a free position (`_grid_positions` skips covered ones) and spans never
  overlap, so a cell's origin and the far corner of its span are always still separate `<w:tc>`s when asked for.
  The random-merge test and the fixtures confirm the output is the same.
- `_merge_cells` uses `CT_Tc._span_to_width`, a private python-docx method (the export already uses `table._tbl`,
  `_Cell` and similar). python-docx is pinned to 1.2.0 in `pyproject.toml`, and the random-merge test compares with
  python-docx's own merge, so an upgrade that changes it fails a test rather than the output.
- Not changed: the paragraph style lookups of non-plain blocks in cells and the body (`_word_style`, `add_paragraph(style=...)`): linear,
  about 2 ms per paragraph, and out of scope for "linear".

## Risks and open questions

- Python-docx internals: see above; the pin and the equality test cover it.
- A table in a cell (nested) is built by the same `_add_table`, so it gets the same fix; checked in the synthetic set.
- Importing a 1000-row table whose cells have two paragraphs is refused by the upload's unpacked-size limit
  (SEC checks), unrelated to this task.
- `scripts/benchmark_table_export.py` imports `app.*` and python-docx only; no database or network.

## Not done / follow-ups

- Per-paragraph style lookup (`get_style_id` scans the styles, ~2 ms) for headings, lists, quotes in cells and for
  every body paragraph: linear but a constant worth caching for big documents with many paragraphs (e.g. a 10,000-paragraph
  document spends about 20 s there). Suggest as a separate task.
- No frontend or API change; no importer output or schema change, so nothing to regenerate.

## Commands run

```
cd backend && /tmp/venv/bin/python -m scripts.benchmark_table_export [--rows ...] [--profile N] [--into-original]
cd backend && /tmp/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_export_scaling.py tests/test_docx_tables.py tests/test_docx_export.py tests/test_original_blocks.py
cd backend && /tmp/venv/bin/python -m pytest -q -p no:cacheprovider        # full suite: 1731 passed, 1 skipped
snap.py / compare.py / synth.py (scratch, base = git archive 370ed49)
```
