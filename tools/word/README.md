# Word checks (Windows, Microsoft Word installed)

The phase gates open what the app writes in real Word: an export Word has to repair fails to open, or counts fewer
objects than its source. They need Python with pywin32 and refuse to run while Word is open (they never close it).
Only open cleaned files and exports this way -- never a file whose source holds active external targets or DDE
fields, since Word would follow them.

1. `gate_exports.py OUT_DIR` (run from `backend/`, with the backend's venv): every Word fixture
   (`backend/tests/fixtures/word`) as an upload keeps it -- cleaned -- and exported two ways: with the academic
   template into that original, and as a new file; prints the package check's findings.
2. `open_check.py FILE...` (with the pywin32 Python): opens each read-only in a hidden Word and prints pictures,
   shapes, equations, paragraphs, tables and pages.
3. `gate_counts.py DIR` (with the pywin32 Python): comments, content controls, form fields, notes, sections, links
   and fields by type for every file in DIR, as JSON. Compare each fixture's cleaned original with its exports.
