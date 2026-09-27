"""Writes each golden Word document (tests/fixtures/documents/), as the importer
reads it, to frontend/tests/fixtures/golden/<name>.json -- the Document the
editor receives. The frontend's tests load it into the real editor and check
the editor gives back the same document (корекции.docx §45: parse -> editor
save/reconciliation). tests/test_golden_documents.py fails when a file here
no longer matches what the importer makes.

    python -m scripts.export_golden_json
"""

import json
import re
import uuid
from pathlib import Path

from app.parsers.docx import parse_docx

BACKEND = Path(__file__).resolve().parent.parent
SOURCE = BACKEND / "tests" / "fixtures" / "documents"
TARGET = BACKEND.parent / "frontend" / "tests" / "fixtures" / "golden"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_WHEN = "2026-01-01T00:00:00Z"


def golden_json(name: str) -> str:
    """The same file for the same importer: ids and times are made stable, so a
    regenerated file only differs where the importer's result did."""
    data = parse_docx((SOURCE / name).read_bytes(), name).model_dump(mode="json")
    data["metadata"]["createdAt"] = data["metadata"]["updatedAt"] = _WHEN
    if data.get("importReport"):
        data["importReport"]["createdAt"] = _WHEN
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    stable: dict[str, str] = {}
    return _UUID.sub(
        lambda match: stable.setdefault(match.group(0), str(uuid.uuid5(uuid.NAMESPACE_URL, f"smartdoc-golden/{name}/{len(stable)}"))),
        text,
    )


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in sorted(SOURCE.glob("*.docx")):
        target = TARGET / f"{path.stem}.json"
        target.write_text(golden_json(path.name), encoding="utf-8")
        print(f"wrote {target.name}")


if __name__ == "__main__":
    main()
