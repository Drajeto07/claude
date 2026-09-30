"""Writes each fixture's expected-loss manifest (tracker TEST-021): what the app says it
changes or leaves out of every golden and Word-authored document, next to it as
<fixture>.expected-loss.json (app/fidelity/loss_manifest.py). Run after a change that
means to change what an import or an export reports, and commit the result; the PDF
claims are kept per platform, this one's replacing its own:

    python -m scripts.export_expected_losses [fixture ...]
"""

import json
import sys
from pathlib import Path

from app.fidelity.loss_manifest import loss_manifest

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FOLDERS = (FIXTURES / "documents", FIXTURES / "word")


def manifest_path(fixture: Path) -> Path:
    return fixture.with_name(fixture.stem + ".expected-loss.json")


def main() -> None:
    only = set(sys.argv[1:])
    for folder in FOLDERS:
        for fixture in sorted(folder.glob("*.docx")):
            if only and fixture.name not in only:
                continue
            path = manifest_path(fixture)
            manifest = loss_manifest(fixture.read_bytes(), fixture.name)
            if path.exists():  # the other platforms' PDF claims stay
                manifest["pdf"] = {**json.loads(path.read_text(encoding="utf-8")).get("pdf", {}), **manifest["pdf"]}
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(f"wrote {path.name}")


if __name__ == "__main__":
    main()
