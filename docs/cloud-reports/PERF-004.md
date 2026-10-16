# PERF-004 — Bounded, compressed version history

Branch `cloud/perf-004-version-history`, from `origin/feature/smartdoc-production-hardening` at `370ed49`.

## Summary

Undo steps (`document_versions`) each held a full JSON copy of the document, bounded only in number. They are now:

- **compressed**: zlib (level 6) of compact UTF-8 JSON in a new column `compressed_data` (`bytea` on Postgres, BLOB on
  SQLite). 12-complex.docx: **49,579 -> 10,021 bytes (4.9x)**, asserted >= 3x in a test.
- **bounded in bytes as well as steps**: new setting `DOCUMENT_HISTORY_MAX_BYTES` (default 10 MB per document,
  compressed). The step bound (`DOCUMENT_HISTORY_MAX_STEPS`, 50) was already there and is unchanged.
- **pictures as asset references only**: inline `data:` pictures could still reach a snapshot (see below); they are now
  moved into assets first.
- older uncompressed rows are **still read** (not converted); the migration's downgrade decompresses compressed rows back.
- the asset sweep decompresses versions when looking for referenced assets; storage metering counts versions as stored.

Restore, undo and redo are unchanged (tested state-for-state).

## Files changed

- `backend/app/db/models/document.py` — `DocumentVersion`: `compressed_data` (new), `legacy_data` (the existing `data`
  column, now nullable), `data` as a property (reads either copy, writes compressed), `stored_bytes` hybrid
  (Python + SQL), check constraint `ck_document_versions_one_copy`; `pack_snapshot` / `unpack_snapshot`.
- `backend/app/services/version_history.py` — retention rule in `_trim` (used after a new step and after a merged
  autosave), `needs_base`.
- `backend/app/services/document_service.py` — `_write` moves leftover inline pictures into assets before recording a
  step (and in the base step of a pre-history document); `_move_inline_images`.
- `backend/app/services/image_assets.py` — `has_inline_images`, `holds_inline_images` (dict walk, no validation).
- `backend/app/services/asset_cleanup.py` — scans compressed and legacy versions.
- `backend/app/services/usage_service.py` — `storage_bytes` adds the versions' stored bytes.
- `backend/app/config.py`, `backend/.env.example` — `document_history_max_bytes`.
- `backend/alembic/versions/b8534d3c4256_document_versions_compressed_data.py` — the migration.
- Tests: `backend/tests/test_version_history_storage.py` (new), `backend/tests/test_db_migration.py` (one test added).
- Docs: `README.md` (Versions, undo/redo and usage paragraphs), `docs/architecture/migration-plan.md` (asset sweep),
  `docs/performance/README.md` (new; section "Version history storage (PERF-004)"), this report.

No API schema changed (`DocumentVersionOut`, `UsageOut` are the same), so the OpenAPI file and frontend types were not
regenerated; `tests/test_openapi_contract.py` passes. Nothing in `frontend/` was touched.

## Design decisions

**zlib, not deltas, not TOAST alone.** Undo/redo/restore/view/compare read one row and decompress it: about 0.8 ms to
read back and 1.4 ms to pack for 12-complex.docx (decompress + JSON parse; measured with timeit on this container).
Deltas would make every read replay a chain and every trim rebase one, and the asset sweep could not read a row on its
own. Postgres TOAST (pglz) already compresses large `jsonb`, but only values over ~2 KB, less well than zlib on JSON,
invisibly to SQLite (tests) and to storage metering; compressed `bytea` is left alone by pglz (it gives up on data that
does not shrink). `ensure_ascii=False` keeps Cyrillic text at 2 bytes per letter instead of 6-byte `\u` escapes.

**Separate column, legacy rows read as they are.** `compressed_data` is added next to `data`; new and merged steps
write only `compressed_data` (`data` NULL), rows from before keep `data`. A check constraint makes every row hold
exactly one of the two. I chose not to convert existing rows in the migration: the upgrade stays schema-only (on
Postgres: ADD COLUMN, DROP NOT NULL, ADD CHECK; quick, no table rewrite) and still renders in offline `--sql` mode,
which `test_every_table_gets_rls_enabled_on_postgres` relies on; the reading path is needed anyway during a rollout.
Live data is tiny (35 versions per `current-baseline.md`), and old rows age out under the same retention rule (except
an original, which is kept forever, uncompressed). A merged autosave into an old row rewrites it compressed.

**Retention rule** (`VersionHistory._trim`). Always kept: the original (1), the current step, the step just below it
(so the last change, a restore included, can always be undone) and every redo step above the current one. `_trim`
only runs from `record()` — after a new step (when redo steps have just been dropped, as before) or a merged autosave
(only at the tip) — never from undo/redo, which only move the pointer. Below the protected steps, undo steps are kept
newest first while they are fewer than `DOCUMENT_HISTORY_MAX_STEPS` and, together with the original and current step,
fit in `DOCUMENT_HISTORY_MAX_BYTES`; everything older is deleted in one `DELETE ... revision_number <= cut`. Undo walks
`current - 1, current - 2, ...` and stops at the first missing number, so a single cut never leaves a reachable step
stranded behind a gap. Sizes come from SQL (`length(compressed_data)`, else `length(data::text)`) without loading any
state; Postgres answers `length(bytea)` from the TOAST header. A restore reads its version before `_write` records
(and trims), so restoring the oldest kept step or the original always works. No "thin older ones" (keeping every n-th
step beyond N): such steps are reachable only by restore, not undo, would add storage, and would change the History
panel's existing contents ([6, 5, 4, 1] in `test_history_depth_is_the_configured_one_plus_the_original`).

**Reachable rows, worked out.** Undo needs `current - 1` downwards, contiguous; redo needs `current + 1` upwards,
contiguous; view/compare/restore need any kept number; nothing else reads versions except the asset sweep (all rows)
and metering (sizes). The step count rule was already bounded (max 50 + original); with the byte rule a document's
history is bounded by min(50 steps, 10 MB) plus the protected rows (which can exceed 10 MB only when a single
document state is that large).

**Inline pictures could still reach a snapshot.** `externalize_inline_images` runs at creation and in the editor's
autosave, but (1) a document saved before pictures moved into storage — or before nested pictures did (commit
`1fe27a9`, 2026-09-27, three days after persisted undo) — still holds them inline, and every other change (rename,
format, restore, ...) stored that state as a step; (2) the base step recorded for a document from before version
history is its pre-change state, inline pictures included. `_write` now moves the document's leftover inline pictures
into assets before recording, and does the same for the base step's state when one is needed. If a legacy document
has more pictures than SEC-012 now allows, they stay inline rather than the change being refused for pictures it did
not add (no data loss; such a step keeps them inline). Invalid inline pictures are removed and reported in
`unsupportedFeatures`, as the autosave path has always done.

**Asset sweep.** `asset_cleanup._ids_used_in_workspace` reads `compressed_data` and `data` and decompresses; the
end-to-end test checks the asset id is *not* findable in the raw compressed bytes, so only a decompressing scan keeps
the picture.

**Metering.** `storage_bytes` = documents' JSON text + versions' stored bytes (compressed, or an old row's JSON
text) + assets. Before, versions were not counted at all, so a workspace's reported storage goes **up** by its history
(about 10 KB per step of a 50 KB document). This is the owner's call to confirm (see open questions).

## Tests added

`backend/tests/test_version_history_storage.py`:

- `test_a_version_of_the_complex_fixture_is_stored_at_least_3x_smaller` (prints the numbers)
- `test_undo_redo_and_restore_give_back_exactly_the_states_that_were_saved`
- `test_versions_stored_before_compression_still_read_and_new_ones_are_compressed`
- `test_an_autosave_merged_into_an_uncompressed_step_rewrites_it_compressed`
- `test_with_no_room_the_original_the_current_step_and_the_one_below_it_stay`
- `test_an_autosave_merging_into_the_current_step_keeps_the_one_below_it`
- `test_an_autosave_growing_the_current_step_past_the_bytes_trims_the_oldest`
- `test_history_past_its_bytes_loses_its_oldest_steps_in_one_cut`
- `test_undo_and_redo_never_trim_the_history`
- `test_by_default_a_real_documents_history_is_bounded_by_steps_not_bytes`
- `test_a_picture_still_inline_in_an_old_document_reaches_no_version`
- `test_the_asset_sweep_keeps_a_picture_only_a_compressed_version_shows`
- `test_storage_counts_the_versions_as_they_are_stored`

`backend/tests/test_db_migration.py`:

- `test_compressed_versions_keep_old_rows_readable_and_the_downgrade_decompresses_them` — on SQLite: upgrade to
  `85211092fe4c`, insert an old-style row, upgrade to `b8534d3c4256`, read it through the ORM, write a compressed row,
  check the constraint, downgrade (both rows come back as JSON, column gone), upgrade to head again and read.

Existing tests unchanged; `test_asset_cleanup.py`'s `DocumentVersion(data=...)` now writes compressed rows, so it
covers the compressed scan too.

## Results

- Targeted: `tests/test_version_history_storage.py tests/test_versioning.py tests/test_db_migration.py
  tests/test_asset_cleanup.py` — 33 passed.
- Full backend suite (HEAD `66ff537`, run from a clean `git archive` copy):
  **`1739 passed, 1 skipped, 2 warnings in 333.61s (0:05:33)`** (the owner's base figure: 1725 passed, 1 skipped; +14 new tests here). The 2
  warnings are Pillow's DecompressionBombWarning in `test_picture_limits.py`, unrelated and pre-existing.
- Frontend: not touched, not run.

## Size numbers

12-complex.docx, as imported (pictures already assets), one version row:

| | bytes |
|---|---|
| before: JSON text as the column stored it (SQLAlchemy JSON on SQLite) | 49,579 |
| after: `compressed_data` | 10,021 |
| ratio | 4.9x |

(The exact numbers shift by a few bytes per run: ids differ.) On Postgres the old size was the `jsonb` value, which
TOAST may already have compressed with pglz; that size was not measured here (no Postgres).

## Mutation checks

Each mutation applied alone, the four test files above run, then restored:

| Mutation | Result |
|---|---|
| M1 byte bound removed | 3 failed |
| M2 step below current not protected (`steps > 1` -> `steps > 0`) | 4 failed |
| M3 original not protected in the trim | 4 failed |
| M4 step-count bound removed | 1 failed |
| M5 legacy (uncompressed) rows unreadable | 3 failed |
| M6 asset sweep scans only uncompressed rows | 2 failed |
| M7 metering ignores versions | 1 failed |
| M8 leftover inline pictures not moved before recording | 1 failed |
| M9 base step's inline pictures not moved | 1 failed |
| M10 downgrade skips decompression | 1 failed |
| M11 trim counts the current step as one below it (`<` -> `<=`) | 2 failed |
| M12 merged autosave not trimmed | 1 failed |

M11 and M12 first survived; the two merge-path tests were added for them.

## Migration

- Revision **`b8534d3c4256`**, `down_revision = '85211092fe4c'`. Exactly one new migration file.
- Upgrade (schema only, `batch_alter_table`): add `document_versions.compressed_data` (LargeBinary, nullable), make
  `data` nullable, add check `ck_document_versions_one_copy`: `(data IS NULL) <> (compressed_data IS NULL)`. Rendered
  Postgres SQL: `ADD COLUMN compressed_data BYTEA; ALTER COLUMN data DROP NOT NULL; ADD CONSTRAINT ... CHECK`.
- Downgrade: decompresses every compressed row into `data` (one row at a time), then drops the check, sets `data` NOT
  NULL and drops `compressed_data`. No version is lost. It needs a live connection and refuses offline `--sql` mode
  with a clear error (it has to read the rows).
- No table created, so no RLS to enable (`test_every_table_gets_rls_enabled_on_postgres` passes).
- Tested on SQLite: upgrade head / downgrade base (existing tests), column-for-column match with the models, and the
  new data round trip above.
- **JOB-001 also adds a migration off `85211092fe4c` on its own branch: whichever of the two merges second must
  re-point its `down_revision` to the other's revision** (otherwise Alembic has two heads).

## Commands run

- `cd backend && /tmp/venv/bin/python -m pytest -q -p no:cacheprovider <files>` (targeted runs; full suite from a
  `git archive HEAD` copy)
- `ALEMBIC_DATABASE_URL=postgresql+asyncpg://offline:offline@localhost/offline python -m alembic upgrade
  85211092fe4c:head --sql` (render only, no server) and the same `downgrade ... --sql` (refuses, as intended)
- the mutation script described above; the secret scan before each push.

## Risks and open questions

- **Metering goes up.** Versions were not counted before; now they are, compressed. A workspace near its plan's
  storage limit may hit it sooner. Owner to confirm this is wanted (the task asked for it).
- **Rolling back the code without the downgrade breaks reading.** Old code reads only `data`, which is NULL for
  compressed rows. Roll back by running the downgrade (`alembic downgrade 85211092fe4c`) first, then deploying the
  old code.
- **Postgres-only behaviour not tested here:** `bytea` through asyncpg, `length(bytea)`/`length(jsonb::text)` in the
  trim and metering queries, the CHECK on existing rows (35 rows; trivial), TOAST behaviour on compressed `bytea`
  (pglz tries and gives up; `ALTER COLUMN compressed_data SET STORAGE EXTERNAL` would skip that attempt — not done,
  untestable here). The SQL used is portable and the offline Postgres render is clean.
- The default 10 MB per document is a judgement call: it never binds for ordinary documents (50 steps of
  12-complex.docx take ~0.5 MB) and keeps a pathological 25 MB-request document to a few steps.
- `length(jsonb::text)` (old rows and `documents.data`) counts characters, not bytes, as `storage_bytes` already did.
- A legacy document whose inline pictures are moved by a non-editor change gets one-time duplicate assets if its base
  step also needed them moved (the copies only the unused base state would use are swept a day later).

## Follow-ups (not in scope)

- An element can arrive with both `image.assetId` and a `data:` `src`; `_is_inline` skips it (it has an asset id), so
  the base64 stays in the document and its steps, outside SEC-012's picture limits. Worth a validator that clears or
  rejects `src` when `assetId` is set (needs care: if the asset id is not the workspace's, the `src` is the only copy).
- `docs/architecture/current-baseline.md`'s Alembic chain lists 8 revisions; left as is (a dated baseline, and JOB-001
  adds one too).

## Not done

- No conversion of existing rows to compressed (by choice, above).
- No Postgres run of anything (rule: SQLite only).
