"""Opens Word files read-only in a hidden Word (never while Word is open) and prints what Word counts in each:
an export that Word had to repair fails to open here, or counts fewer objects than its source."""
import subprocess
import sys

import win32com.client as win32


def running(image: str) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return any(line.startswith(f'"{image}"') for line in out.splitlines())


if running("WINWORD.EXE"):
    sys.exit("Word is open - not automating it")
word = win32.DispatchEx("Word.Application")
try:
    word.Visible = False
    word.DisplayAlerts = 0
    for path in sys.argv[1:]:
        try:
            # FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, ..., OpenAndRepair=False, ..., NoEncodingDialog
            doc = word.Documents.Open(path, False, True, False, "", "", False, "", "", 0, 0, False, False, 0, True)
        except Exception as exc:  # noqa: BLE001
            print(f"{path}: FAILED TO OPEN: {exc}")
            continue
        counts = {
            "inline_shapes": doc.InlineShapes.Count,
            "shapes": doc.Shapes.Count,
            "omaths": doc.OMaths.Count,
            "paragraphs": doc.Paragraphs.Count,
            "tables": doc.Tables.Count,
            "pages": doc.ComputeStatistics(2),
        }
        kinds = {}
        for index in range(1, doc.InlineShapes.Count + 1):
            kind = doc.InlineShapes(index).Type
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"{path.rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1]}: {counts} inline types {dict(sorted(kinds.items()))}")
        doc.Close(False)
finally:
    word.Quit()
