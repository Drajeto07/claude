"""The true fidelity test (tracker TEST-022, audit AUD-20): every fixture through the
app's whole path -- imported as an upload imports it, formatted with the academic
template, saved as the editor saves it, exported to Word into the original -- and the
Word file that came out against the one that went in, on each axis on its own:
content, structure, formatting, metadata (app/fidelity/round_trip.py). What each axis
differs in today is pinned in <fixture>.expected-fidelity.json; anything else -- a new
difference, or one that went away -- fails, on its axis, until the manifest is
rewritten on purpose (`python -m scripts.export_expected_fidelity`)."""

import json
from functools import cache

import pytest

from scripts.export_expected_fidelity import expected, manifest_path
from scripts.export_expected_losses import FOLDERS

FIXTURES = [fixture for folder in FOLDERS for fixture in sorted(folder.glob("*.docx"))]
AXES = ("content", "structure", "formatting", "metadata")


@cache
def _actual(fixture):
    return expected(fixture)


def test_every_fixture_has_a_fidelity_manifest():
    assert [fixture.name for fixture in FIXTURES if not manifest_path(fixture).exists()] == []


@pytest.mark.parametrize("axis", AXES)
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.name)
def test_what_comes_out_is_what_went_in(fixture, axis):
    pinned = json.loads(manifest_path(fixture).read_text(encoding="utf-8"))
    actual = _actual(fixture)

    assert actual["template"] == pinned["template"]
    if axis == "content":
        assert actual[axis] == pinned[axis]
    else:
        new = [line for line in actual[axis] if line not in pinned[axis]]
        gone = [line for line in pinned[axis] if line not in actual[axis]]
        assert (new, gone) == ([], []), f"{axis} -- new: {new}; gone: {gone}"
