"""Phase 4 gate: each Word fixture as an upload now keeps it -- cleaned (SEC-015 fields,
SEC-016 external targets) -- then exported two ways from that: through the app's whole path
with the academic template, into the cleaned original, and as a new Word file. Writes the
cleaned file and both exports for the Word checks, and runs the package check.
Run from backend/: python ../tools/word/gate_exports.py OUT_DIR"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from app.export.docx_export import build_docx  # noqa: E402
from app.export.package_check import package_problems  # noqa: E402
from app.export.provenance import stamp  # noqa: E402
from app.fidelity.round_trip import through_the_app  # noqa: E402
from app.formatting.engine import recompute_styles  # noqa: E402
from app.formatting.templates import BUILTIN_TEMPLATES  # noqa: E402
from app.parsers.docx import parse_docx  # noqa: E402
from app.security.package import clean_package  # noqa: E402

TEMPLATE = BUILTIN_TEMPLATES["academic-default"]
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
problems, cleaned_counts = {}, {}
for fixture in sorted(Path("tests/fixtures/word").glob("*.docx")):
    cleaned = clean_package(fixture.read_bytes())
    if cleaned.fields or cleaned.links or cleaned.external:
        cleaned_counts[fixture.stem] = (cleaned.fields, cleaned.links, cleaned.external)
    data = cleaned.data
    _, templated = through_the_app(data, fixture.name, template_id=TEMPLATE.id, template_rules=TEMPLATE.rules)
    document = parse_docx(data, fixture.name)
    recompute_styles(document)
    stamp(document)
    fresh = build_docx(document)
    (out / f"{fixture.stem}.cleaned.docx").write_bytes(data)
    (out / f"{fixture.stem}.template.docx").write_bytes(templated)
    (out / f"{fixture.stem}.new.docx").write_bytes(fresh)
    for label, written in (("cleaned", data), ("template", templated), ("new", fresh)):
        found = package_problems(written)
        if found:
            problems[f"{fixture.stem}.{label}"] = found
print("written", len(list(out.glob("*.docx"))), "files; cleaned (fields, links, external):", cleaned_counts or "none")
print("package problems:", problems or "none")
