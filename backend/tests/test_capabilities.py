"""The capability matrix (tracker CORE-004) stays true to the code: every
fidelity feature key the code reports is described, every key it describes is
reported somewhere, every test it cites exists, and nothing claims a clean round
trip without a test behind it."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.capabilities import MATRIX
from app.fidelity.exports import _KEPT_IN_PDF
from app.main import app
from app.parsers.docx import _KEPT_NOTES

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
# A feature key as the code writes it: "docx.image.linked", "export.pdf.script"...
_KEY = re.compile(r"""["']((?:docx|export|pdf|paste|txt|markdown)\.[a-z_]+(?:\.[a-z_]+)*)["']""")


def _reported_keys() -> set[str]:
    keys: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name in ("capabilities.py", "report.py"):  # the matrix itself; report.py only names examples
            continue
        keys |= set(_KEY.findall(path.read_text(encoding="utf-8")))
    # Keys the code builds from a name.
    keys |= {f"docx.{kind}" for kind in _KEPT_NOTES}
    keys |= {f"export.pdf.{kind}" for kind in _KEPT_IN_PDF}
    keys |= {f"{source}.note" for source in ("paste", "txt", "pdf")}
    return keys


def _described_keys() -> set[str]:
    return {key for capability in MATRIX.capabilities for key in capability.features}


def test_every_key_the_code_reports_is_described():
    assert _reported_keys() - _described_keys() == set()


def test_every_described_key_is_reported_somewhere():
    assert _described_keys() - _reported_keys() == set()


def test_every_cited_test_exists():
    missing = []
    for capability in MATRIX.capabilities:
        for reference in capability.tests:
            if reference.startswith("frontend/"):
                if not (REPOSITORY / reference).is_file():
                    missing.append(reference)
                continue
            file, _, name = reference.partition("::")
            path = BACKEND / file
            if not path.is_file() or not re.search(rf"^(?:async )?def {re.escape(name)}\(", path.read_text(encoding="utf-8"), re.M):
                missing.append(reference)
    assert missing == []


def test_a_clean_round_trip_is_never_claimed_without_a_test():
    assert [c.id for c in MATRIX.capabilities if c.roundTrip == "yes" and not c.tests] == []


def test_ids_are_unique_and_gaps_are_explained():
    ids = [capability.id for capability in MATRIX.capabilities]
    assert len(ids) == len(set(ids))
    # A feature nothing reports yet must say so, and name the task that will.
    silent = [c for c in MATRIX.capabilities if c.policy == "not_detected"]  # none since EDIT-010
    assert all(re.search(r"\((?:[A-Z]+-\d{3}[A-Z]?)\)", c.notes) or "content check" in c.notes for c in silent), [
        c.id for c in silent if not re.search(r"\([A-Z]+-\d{3}", c.notes)
    ]


def test_the_matrix_is_served_to_anyone():
    client = TestClient(app, base_url="https://testserver")
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    rows = response.json()["capabilities"]
    assert len(rows) == len(MATRIX.capabilities)
    links = next(row for row in rows if row["id"] == "docx.hyperlinks")
    assert (links["import"], links["edit"], links["export"], links["roundTrip"]) == ("yes", "yes", "yes", "yes")
