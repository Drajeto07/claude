"""scripts/benchmark.py (PERF-002) isn't part of the test run, but a script nobody runs
rots: this runs each of its cases on the smallest input, in this process, and checks
the report that comes out of them."""

import argparse

from scripts import benchmark


def test_a_synthetic_document_is_made_of_what_its_name_says():
    assert len(benchmark.synthetic("blocks-30")) == 30
    table = next(element for element in benchmark.synthetic("table-4x3") if element["type"] == "table")
    assert [len(row["cells"]) for row in table["table"]["rows"]] == [3, 3, 3, 3]
    pictures = [element for element in benchmark.synthetic("pictures-3") if element["type"] == "image"]
    assert len(pictures) == 3 and all(element["image"]["src"].startswith("data:image/png;base64,") for element in pictures)


def test_import_save_load_and_export_run_on_a_tiny_case():
    imported = benchmark.case_import("documents", 1, limit=1)["items"][0]
    assert imported["blocks"] > 0 and imported["best_s"] > 0 and imported["peak_kib"] > 0

    api = benchmark.case_save_load("blocks-30", 1)
    assert api["save"]["best_s"] > 0 and api["load"]["response_bytes"] > 0
    assert api["load"]["content_type"].startswith("application/json")
    assert api["stored"]["document_bytes"] > 0 and api["stored"]["version_rows"] >= 1
    assert api["stored"]["version_bytes"] > 0  # compressed rows counted too (PERF-004)

    for kind in ("docx", "pdf"):
        assert benchmark.case_export("blocks-30", kind, 1)["output_bytes"] > 0


def test_a_case_that_takes_too_long_is_reported_not_waited_for():
    outcome = benchmark.run_case(["save-load", "blocks-30"], argparse.Namespace(timeout=0.05, limit=None), 1)

    assert outcome["status"] == "timeout" and "limit" in outcome["note"]


def test_the_report_names_what_did_not_finish():
    report = {
        "generated": "now",
        "machine": {"cpu": "cpu", "cores": 1, "ram_gib": 1, "os": "os", "python": "3", "git_commit": "abc"},
        "options": "options",
        "results": [{"id": "export/docx/table-500x8", "group": "export", "status": "timeout", "note": "killed after the 600 s limit", "wall_s": 600.0}],
    }

    text = benchmark.render_markdown(report)

    assert "## Not finished" in text and "export/docx/table-500x8" in text and "timeout" in text
