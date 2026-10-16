"""Phase 4 gate, second Word pass: opens each cleaned original and its two exports read-only in a hidden Word
(never while Word is open) and prints what Word counts of the things cleaning must not touch: comments,
content controls, form fields, notes, sections, links, and the fields by type. Usage: python word_gate_counts.py DIR"""
import json
import subprocess
import sys
from pathlib import Path

import win32com.client as win32


def running(image: str) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return any(line.startswith(f'"{image}"') for line in out.splitlines())


def story_fields(doc):
    kinds = {}
    for story in doc.StoryRanges:
        current = story
        while current is not None:
            for index in range(1, current.Fields.Count + 1):
                kind = current.Fields(index).Type
                kinds[kind] = kinds.get(kind, 0) + 1
            try:
                current = current.NextStoryRange
            except Exception:  # noqa: BLE001
                current = None
    return dict(sorted(kinds.items()))


if running("WINWORD.EXE"):
    sys.exit("Word is open - not automating it")
folder = Path(sys.argv[1])
results = {}
word = win32.DispatchEx("Word.Application")
try:
    word.Visible = False
    word.DisplayAlerts = 0
    for path in sorted(folder.glob("*.docx")):
        try:
            doc = word.Documents.Open(str(path), False, True, False, "", "", False, "", "", 0, 0, False, False, 0, True)
        except Exception as exc:  # noqa: BLE001
            results[path.name] = f"FAILED TO OPEN: {exc}"
            continue
        results[path.name] = {
            "comments": doc.Comments.Count,
            "controls": doc.ContentControls.Count,
            "form_fields": doc.FormFields.Count,
            "footnotes": doc.Footnotes.Count,
            "endnotes": doc.Endnotes.Count,
            "sections": doc.Sections.Count,
            "hyperlinks": doc.Hyperlinks.Count,
            "fields": story_fields(doc),
        }
        doc.Close(False)
finally:
    word.Quit()
print(json.dumps(results, indent=1))
