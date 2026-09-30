"""Writes each fixture's expected-fidelity manifest (tracker TEST-022): how the Word
file that comes out of the app's whole path (import, the academic template, an editor
save, a Word export) differs from the one that went in, on each axis -- content,
structure, formatting, metadata (app/fidelity/round_trip.py) -- next to the fixture
as <fixture>.expected-fidelity.json. Run after a change that means to change them,
and commit the result:

    python -m scripts.export_expected_fidelity [fixture ...]
"""

import json
import sys

from app.fidelity.round_trip import fidelity
from app.formatting.templates import BUILTIN_TEMPLATES
from scripts.export_expected_losses import FOLDERS

TEMPLATE = BUILTIN_TEMPLATES["academic-default"]


def manifest_path(fixture):
    return fixture.with_name(fixture.stem + ".expected-fidelity.json")


def expected(fixture) -> dict:
    return fidelity(fixture.read_bytes(), fixture.name, template_id=TEMPLATE.id, template_rules=TEMPLATE.rules)


def main() -> None:
    only = set(sys.argv[1:])
    for folder in FOLDERS:
        for fixture in sorted(folder.glob("*.docx")):
            if only and fixture.name not in only:
                continue
            manifest_path(fixture).write_text(json.dumps(expected(fixture), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"wrote {manifest_path(fixture).name}")


if __name__ == "__main__":
    main()
