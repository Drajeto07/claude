"""Every fixture loses what its manifest says, and nothing else (tracker TEST-021, audit
AUD-20): its import report and its Word and PDF exports' reports -- each item's
feature, policy, count and whether it changes content, and the content checks'
status -- against <fixture>.expected-loss.json. A new loss, or one that went away,
fails here until the manifest is rewritten on purpose
(`python -m scripts.export_expected_losses`). A PDF's claims depend on the fonts the
machine has, so they are compared where they were recorded."""

import json
import sys
from pathlib import Path

import pytest

from app.fidelity.loss_manifest import loss_manifest
from scripts.export_expected_losses import FOLDERS, manifest_path

FIXTURES = [fixture for folder in FOLDERS for fixture in sorted(folder.glob("*.docx"))]


def _difference(stage: str, expected: dict, actual: dict) -> list[str]:
    """What changed in one stage's claims, in words."""
    lines = []
    if expected["content"] != actual["content"]:
        lines.append(f"{stage}: content {expected['content']} -> {actual['content']}")
    key = lambda item: (item["feature"], item["policy"])  # noqa: E731
    before, after = {key(item): item for item in expected["items"]}, {key(item): item for item in actual["items"]}
    for feature, policy in sorted(after.keys() - before.keys()):
        lines.append(f"{stage}: new {feature} ({policy})")
    for feature, policy in sorted(before.keys() - after.keys()):
        lines.append(f"{stage}: gone {feature} ({policy})")
    for item in sorted(before.keys() & after.keys()):
        if before[item] != after[item]:
            lines.append(f"{stage}: {item[0]} {before[item]} -> {after[item]}")
    return lines


def test_every_fixture_has_a_manifest():
    assert len(FIXTURES) >= 37
    assert [fixture.name for fixture in FIXTURES if not manifest_path(fixture).exists()] == []


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.name)
def test_a_fixture_loses_what_its_manifest_says(fixture):
    expected = json.loads(manifest_path(fixture).read_text(encoding="utf-8"))
    actual = loss_manifest(fixture.read_bytes(), fixture.name)

    differences = _difference("import", expected["import"], actual["import"]) + _difference("docx", expected["docx"], actual["docx"])
    if sys.platform in expected.get("pdf", {}):
        differences += _difference("pdf", expected["pdf"][sys.platform], actual["pdf"][sys.platform])
    assert differences == [], "\n".join(differences)


def test_another_platforms_pdf_claims_are_merged_in_and_nothing_else(tmp_path):
    """TEST-021A: CI records Linux's PDF claims as an artifact; merging takes only those."""
    from scripts.merge_expected_losses import merge

    here, downloaded = tmp_path / "here", tmp_path / "artifact" / "tests" / "fixtures" / "word"
    here.mkdir()
    downloaded.mkdir(parents=True)
    ours = {"import": {"items": ["ours"]}, "docx": {"items": []}, "pdf": {"win32": {"items": ["win"]}}}
    theirs = {"import": {"items": ["changed there"]}, "docx": {"items": ["x"]}, "pdf": {"win32": {"items": ["other"]}, "linux": {"items": ["lin"]}}}
    (here / "a.expected-loss.json").write_text(json.dumps(ours), encoding="utf-8")
    (downloaded / "a.expected-loss.json").write_text(json.dumps(theirs), encoding="utf-8")

    assert merge(tmp_path / "artifact", "linux", (here,)) == ["a.expected-loss.json"]
    merged = json.loads((here / "a.expected-loss.json").read_text(encoding="utf-8"))
    assert merged == {**ours, "pdf": {"win32": {"items": ["win"]}, "linux": {"items": ["lin"]}}}
    assert merge(tmp_path / "artifact", "linux", (here,)) == []  # already in
