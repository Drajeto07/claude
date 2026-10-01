# Performance

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
`docs/cloud-reports/PERF-001.md`.

Check it:

- `cd backend && python -m scripts.benchmark_table_export` prints the time for 250, 500 and 1000 rows of 8 columns
  and runs the package check on each result (`--into-original` exports into the imported file, `--profile` prints
  the most expensive functions, `--rows` and `--columns` change the sizes).
- `backend/tests/test_export_scaling.py` runs in a few seconds: the time at four times the rows must stay well
  under the square's (a ratio, so a slow machine passes), the export must not use `table.cell()`, `cell.merge()` or
  the whole-table lookups behind them, merging must equal python-docx's, and the table that comes out must be the
  one made cell by cell.

Not covered: a cell's paragraphs other than plain ones (headings, lists, quotes inside a cell) still look their
style up per paragraph. That is linear, about 2 ms each.
