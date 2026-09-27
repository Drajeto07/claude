# Testing

| Layer | Where | Run |
|---|---|---|
| Backend unit + API | `backend/tests/` (pytest; the API tests use a fresh test database, never the real one) | `cd backend && venv/Scripts/python -m pytest -q -p no:cacheprovider` |
| Frontend unit + editor mapping | `frontend/**/*.test.ts(x)` (Vitest, jsdom, the real Tiptap editor) | `cd frontend && npx vitest run` |
| Types + lint | | `cd frontend && npx tsc --noEmit && npx eslint .` |
| End to end | `frontend/e2e/` (Playwright; starts `scripts.e2e_server` on a fresh SQLite at :8100 and `next build && next start` at :3100) | `cd frontend && npx playwright test` |

`next build` type-checks test files too, so run `npx tsc --noEmit` before the end-to-end suite.

## Golden documents

`backend/tests/fixtures/documents/*.docx` are 12 synthetic Word files built by `scripts/make_golden_documents.py`. A
test checks the committed files still match what the builder makes.

`python -m scripts.export_golden_json` (in `backend/`) writes what the importer makes of each one to
`frontend/tests/fixtures/golden/*.json`. The output is deterministic (stable ids and times), so a regenerated file
only differs where the importer's result did. `test_the_frontend_golden_json_is_current` fails when it's stale.

The frontend loads these into the real editor (`editor/editorRoundTrip.test.ts`) and checks two things:
- each document comes back unchanged;
- opening it produces nothing of its own to save, and nothing it can't keep.

## Fidelity tests

- `tests/test_fidelity_report.py`: the content check, calibrated on the golden documents plus Word-authored audit
  documents (those stay outside the repository, TEST-020).
- `tests/test_docx_detect.py`, `test_docx_numbering.py`, `test_link_titles.py`, `test_markdown_parser.py`: each
  detection and each kept feature.
- `tests/test_capabilities.py`: the capability matrix against the code.
- `tests/test_rule_values.py`, `test_editor_direct_styles.py`: rule values and the editor's own formatting.
- `frontend/editor/nestedBlocks.test.ts`, `directFormatting.test.ts`, `useAutoSave.test.tsx`: the editor's side.
- `frontend/e2e/nested.spec.ts`, `direct-formatting.spec.ts`: paste → save → reload in a real browser.

## Word files the app writes

`app/export/package_check.py::package_problems` (TEST-023) checks a Word file's package independently of
python-docx. It finds what makes Word refuse a file or open it "with unreadable content". `tests/test_package_check.py`
runs it on every golden document's export, fresh and written into its original (DOCX-011), and shows it catches each
kind of damage. The docx skill's XSD validator needs `defusedxml`, which isn't installed here; this check covers the
package consistency Word itself enforces.

## Checking by hand in a browser

Use the throwaway stack, which has a fresh SQLite database and no real data:
- `tools/dev/throwaway-backend.ps1` (:8100) and `tools/dev/throwaway-frontend.ps1` (:3100);
- or the `backend-throwaway` / `frontend-throwaway` configurations in `.claude/launch.json`.

Never use the `backend` configuration: it uses the real database. Stop the throwaway stack before running the
end-to-end suite, because it uses the same ports.
