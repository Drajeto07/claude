# Performance

What was measured, what was changed for it, and the numbers. One section per task.

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
