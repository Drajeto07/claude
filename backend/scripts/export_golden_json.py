"""Writes each golden Word document (tests/fixtures/documents/), as the importer
reads it, to frontend/tests/fixtures/golden/<name>.json -- the Document the
editor receives. The frontend's tests load it into the real editor and check
the editor gives back the same document (корекции.docx §45: parse -> editor
save/reconciliation). tests/test_golden_documents.py fails when a file here
no longer matches what the importer makes.

    python -m scripts.export_golden_json
"""

import json
from pathlib import Path

from app.parsers.docx import parse_docx

BACKEND = Path(__file__).resolve().parent.parent
SOURCE = BACKEND / "tests" / "fixtures" / "documents"
TARGET = BACKEND.parent / "frontend" / "tests" / "fixtures" / "golden"


def golden_json(name: str) -> str:
    document = parse_docx((SOURCE / name).read_bytes(), name)
    return json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=1) + "\n"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in sorted(SOURCE.glob("*.docx")):
        target = TARGET / f"{path.stem}.json"
        target.write_text(golden_json(path.name), encoding="utf-8")
        print(f"wrote {target.name}")


if __name__ == "__main__":
    main()
