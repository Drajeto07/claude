"""Writes the API's OpenAPI schema to frontend/types/generated/openapi.json, the
source of the frontend's generated types:

    .\\venv\\Scripts\\python.exe -m scripts.export_openapi
    cd ..\\frontend; npm run generate-types

The schema comes from the code alone (no database or running server). The file is
committed, so a change to the API shows up in review, and
tests/test_openapi_contract.py fails while it is out of date."""

import json
from pathlib import Path

from app.main import app

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "frontend" / "types" / "generated" / "openapi.json"


def schema_text() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    SCHEMA_FILE.write_text(schema_text(), encoding="utf-8", newline="\n")
    print(f"Wrote {SCHEMA_FILE}")


if __name__ == "__main__":
    main()
