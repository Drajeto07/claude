"""Writes the PDF export's font fallbacks for the editor (tracker FONT-005):
frontend/editor/fontFallbacks.json -- the kind hints, the fonts made with a common one's widths
(METRIC_COMPATIBLE) and the best fonts of each kind, as app/export/fonts.py has them, so the
editor's CSS stacks stand in the same fonts, in the same order, as a PDF export draws.
tests/test_font_fallbacks.py fails when the file no longer matches.

    python -m scripts.export_font_fallbacks
"""

import json
from pathlib import Path

from app.export import fonts

TARGET = Path(__file__).resolve().parent.parent.parent / "frontend" / "editor" / "fontFallbacks.json"


def font_fallbacks_json() -> str:
    data = {
        "hints": {"mono": list(fonts._MONO_HINTS), "serif": list(fonts._SERIF_HINTS)},
        "metricCompatible": {name: list(names) for name, names in fonts.METRIC_COMPATIBLE.items()},
        "kinds": {kind: list(names) for kind, names in fonts._FALLBACKS.items()},
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main() -> None:
    TARGET.write_text(font_fallbacks_json(), encoding="utf-8")
    print(f"wrote {TARGET.name}")


if __name__ == "__main__":
    main()
