"""Saving what changed (tracker PERF-003): PATCH /content takes the top-level elements
changed, added and removed since the revision in If-Match, saves the list they make as
PUT /content saves a whole one, and answers with how the stored document now differs
from that revision -- which, applied to it, gives the stored document exactly."""

import base64
import io
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.main import app
from app.models.document import Element, ElementType
from app.services.content_patch import PatchMismatchError, content_delta, patched_elements
from tests.fakes import FakeAIProvider
from tests.helpers import error_body
from tests.test_field_policy import _DOCX, _fragment, _word_file

client = TestClient(app, base_url="https://testserver")
_TEXT = "# Report\n\nThe first paragraph.\n\n## Method\n\nThe second paragraph.\n\nThe third paragraph.\n"


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)
    assert client.post("/api/v1/auth/register", json={"email": "patch@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _element(element_id: str) -> Element:
    return Element(id=element_id, type=ElementType.PARAGRAPH, content=element_id, order=0)


def _ids(elements: list[Element]) -> list[str]:
    return [element.id for element in elements]


# -- building the list ------------------------------------------------------------


def test_a_patch_makes_the_list_from_the_stored_one():
    stored = [_element(name) for name in "abcd"]
    changed = Element(id="b", type=ElementType.HEADING, content="B", order=7, level=2)

    result = patched_elements(
        stored,
        changed=[changed],
        added=[(None, _element("x")), ("x", _element("y")), ("c", _element("z"))],
        removed=["d"],
    )

    assert _ids(result) == ["x", "y", "a", "b", "c", "z"]
    assert result[3] is changed and result[2] is stored[0]


@pytest.mark.parametrize(
    ("changed", "added", "removed"),
    [
        (["q"], [], []),  # changes a block that isn't there
        (["a"], [], ["a"]),  # changes one it removes
        (["a", "a"], [], []),
        ([], [], ["q"]),  # removes one that isn't there
        ([], [], ["a", "a"]),
        ([], [("a", "b")], []),  # adds one that is there
        ([], [("a", "x"), ("x", "x")], []),  # adds the same one twice
        ([], [("q", "x")], []),  # after one that isn't there
        ([], [("c", "x")], ["c"]),  # after one it removes
        ([], [("y", "x"), ("a", "y")], []),  # after one that comes later
        ([], [("a", "x"), ("a", "y")], []),  # two in the same place
        ([], [(None, "x"), (None, "y")], []),
    ],
)
def test_a_patch_that_doesn_t_fit_is_refused(changed, added, removed):
    stored = [_element(name) for name in "abc"]
    with pytest.raises(PatchMismatchError):
        patched_elements(stored, changed=[_element(name) for name in changed], added=[(after, _element(name)) for after, name in added], removed=removed)


def test_the_answer_holds_only_what_changed():
    before = {"elements": [{"id": "a", "order": 0, "content": "A"}, {"id": "b", "order": 1, "content": "B"}], "metadata": {"t": 1}, "rules": [1]}
    after = {
        "elements": [{"id": "x", "order": 0, "content": "X"}, {"id": "a", "order": 1, "content": "A"}],
        "metadata": {"t": 2},
        "rules": [1],
    }

    delta = content_delta(before, after, ["x", "a"])

    # "a" only moved down one place: its order is the editor's to work out.
    assert delta == {"changed": [{"id": "x", "order": 0, "content": "X"}], "order": None, "fields": {"metadata": {"t": 2}}}
    assert content_delta(before, after, ["a", "x"])["order"] == ["x", "a"]


# -- through the API --------------------------------------------------------------


def _merged(base: dict, order: list[str], saved: dict) -> dict:
    """What the editor makes of an answer (editor/contentPatch.ts applyContentSaved)."""
    by_id = {element["id"]: element for element in base["elements"]}
    for element in saved["changed"]:
        by_id[element["id"]] = element
    elements = [{**by_id[element_id], "order": index} for index, element_id in enumerate(saved["order"] or order)]
    return {**base, **saved["fields"], "elements": elements, "revision": saved["revision"]}


def _patch(base: list[dict], new: list[dict]) -> dict:
    """What the editor sends for `new` (editor/contentPatch.ts contentPatch)."""
    was = {element["id"]: {key: value for key, value in element.items() if key != "order"} for element in base}
    present = {element["id"] for element in new}
    changed, added = [], []
    for index, element in enumerate(new):
        if element["id"] not in was:
            added.append({"after": new[index - 1]["id"] if index else None, "element": element})
        elif was[element["id"]] != {key: value for key, value in element.items() if key != "order"}:
            changed.append(element)
    return {"changed": changed, "added": added, "removed": [element["id"] for element in base if element["id"] not in present]}


def _paragraph(text: str) -> dict:
    return {"id": str(uuid.uuid4()), "type": "paragraph", "content": text, "order": 0, "inline": [{"text": text, "marks": []}]}


def _picture() -> dict:
    buffer = io.BytesIO()
    PILImage.new("RGB", (4, 3), (10, 120, 200)).save(buffer, format="PNG")
    src = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    return {"id": str(uuid.uuid4()), "type": "image", "content": "", "order": 0, "image": {"src": src}}


_EDITS = ("type", "insert", "delete", "level", "picture", "align", "several")


def _edit(rng: random.Random, elements: list[dict]) -> tuple[list[dict], list[dict], str]:
    """One random edit, as the editor would hold it: the new list, the direct styles,
    and which kind of edit it was."""
    new = [dict(element) for element in elements]
    texts = [index for index, element in enumerate(new) if element["type"] in ("paragraph", "heading")]
    kind = rng.choice(("type",) + _EDITS)
    styles: list[dict] = []
    if kind == "type" and texts:
        index = rng.choice(texts)
        text = f"{new[index]['content']} {rng.randint(0, 999)}"
        new[index] = {**new[index], "content": text, "inline": [{"text": text, "marks": []}]}
    elif kind == "insert":
        new.insert(rng.randint(0, len(new)), _paragraph(f"Inserted {rng.randint(0, 999)}."))
    elif kind == "delete" and len(new) > 2:
        del new[rng.randrange(len(new))]
    elif kind == "level":
        headings = [index for index, element in enumerate(new) if element["type"] == "heading"]
        if headings:
            index = rng.choice(headings)
            new[index] = {**new[index], "level": 2 if new[index].get("level") == 1 else 1}
    elif kind == "picture":
        new.insert(rng.randint(0, len(new)), _picture())
    elif kind == "align" and texts:
        styles = [{"elementId": new[rng.choice(texts)]["id"], "property": "alignment", "value": rng.choice(["center", "right"]), "unit": None}]
    elif kind == "several":
        at = rng.randint(0, len(new))
        new[at:at] = [_paragraph(f"Pasted {n}.") for n in range(rng.randint(2, 4))]
        if len(new) > 4:
            del new[rng.randrange(len(new))]
    for index, element in enumerate(new):
        element["order"] = index
    return new, styles, kind


def _comparable(document: dict) -> dict:
    """The parts a save decides, with what is per document left out (asset ids)."""

    def element(value):
        if isinstance(value, dict):
            image = value.get("image")
            if image and image.get("assetId"):
                value = {**value, "image": {**image, "assetId": "<asset>"}}
            return {key: element(item) for key, item in value.items()}
        if isinstance(value, list):
            return [element(item) for item in value]
        return value

    rules = sorted((rule["target"], rule["property"], rule["value"], rule["priority"]) for rule in document["formattingRules"])
    return {"elements": element(document["elements"]), "resolvedStyles": document["resolvedStyles"], "rules": rules}


def test_a_patch_stores_what_a_whole_save_stores_and_its_answer_gives_the_stored_document(signed_in):
    patched = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    whole = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    whole = client.put(f"/api/v1/documents/{whole['id']}/content", json={"elements": patched["elements"]}).json()
    rng = random.Random(20261001)
    kinds = set()

    for step in range(40):
        base = client.get(f"/api/v1/documents/{patched['id']}").json()
        new, styles, kind = _edit(rng, base["elements"])
        kinds.add(kind)
        asked = [element["id"] for element in new]

        answer = client.patch(
            f"/api/v1/documents/{patched['id']}/content", json={**_patch(base["elements"], new), "styles": styles}, headers={"If-Match": str(base["revision"])}
        )
        assert answer.status_code == 200, (step, answer.text[:300])
        stored = client.get(f"/api/v1/documents/{patched['id']}").json()
        assert _merged(base, asked, answer.json()) == stored, step

        whole = client.put(f"/api/v1/documents/{whole['id']}/content", json={"elements": new, "styles": styles}).json()
        assert _comparable(stored) == _comparable(whole), step
        assert stored["revision"] == answer.json()["revision"] == base["revision"] + 1
    assert kinds == set(_EDITS)


def test_a_one_paragraph_change_in_a_long_document_sends_and_gets_back_that_paragraph(signed_in):
    text = "# Long\n\n" + "\n\n".join(f"Paragraph {n} of a long document, with a sentence or two in it." for n in range(400))
    document = client.post("/api/v1/documents", json={"text": text}).json()
    edited = dict(document["elements"][200], content="Changed.", inline=[{"text": "Changed.", "marks": []}])
    new = [edited if element["id"] == edited["id"] else element for element in document["elements"]]
    patch = _patch(document["elements"], new)

    answer = client.patch(f"/api/v1/documents/{document['id']}/content", json=patch, headers={"If-Match": str(document["revision"])})

    assert answer.status_code == 200
    whole = len(client.get(f"/api/v1/documents/{document['id']}").content)
    assert [element["id"] for element in answer.json()["changed"]] == [edited["id"]]
    assert len(answer.request.content) < whole / 50 and len(answer.content) < whole / 50


def test_a_patch_names_its_revision_and_one_that_doesn_t_fit_writes_nothing(signed_in):
    document = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    path = f"/api/v1/documents/{document['id']}/content"
    versions = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    unknown = {"changed": [dict(document["elements"][1], id="not-there")]}

    without = client.patch(path, json={"removed": [document["elements"][1]["id"]]})
    stale = client.patch(path, json={"removed": [document["elements"][1]["id"]]}, headers={"If-Match": str(document["revision"] - 1)})
    mismatch = client.patch(path, json=unknown, headers={"If-Match": str(document["revision"])})

    assert (without.status_code, error_body(without)["code"]) == (428, "precondition_required")
    assert (stale.status_code, error_body(stale)["code"]) == (412, "revision_conflict")
    assert (mismatch.status_code, error_body(mismatch)["code"]) == (409, "patch_mismatch")
    assert client.get(f"/api/v1/documents/{document['id']}").json() == document
    assert client.get(f"/api/v1/documents/{document['id']}/versions").json() == versions


def test_a_patch_can_t_add_what_a_whole_save_can_t(signed_in):
    """The server's preserved fragments and provenance stay its own (SEC-015, DOCX-028),
    for a changed block and an added one alike."""
    upload = client.post("/api/v1/documents/upload", files={"file": ("fields.docx", _word_file(), _DOCX)}).json()
    dated = next(element for element in upload["elements"] if element["content"].startswith("Printed on"))
    kept = {key: dated[key] for key in ("preservedAttributes", "sourceBlocks", "sourceHash")}
    crafted = {**dated, "preservedAttributes": {"ooxml": [_fragment(" DDEAUTO cmd /k calc ", "Printed")]}, "sourceBlocks": [999], "sourceHash": "0" * 64}
    new = {**_paragraph("Some text."), "preservedAttributes": {"ooxml": [_fragment(" DDEAUTO cmd ")]}, "sourceBlocks": [999], "sourceHash": "0" * 64}

    answer = client.patch(
        f"/api/v1/documents/{upload['id']}/content",
        json={"changed": [crafted], "added": [{"after": upload["elements"][-1]["id"], "element": new}]},
        headers={"If-Match": str(upload["revision"])},
    )

    assert answer.status_code == 200, answer.text[:300]
    stored = {element["id"]: element for element in client.get(f"/api/v1/documents/{upload['id']}").json()["elements"]}
    assert {key: stored[dated["id"]][key] for key in kept} == kept
    assert [stored[new["id"]][key] for key in kept] == [None, None, None]


def test_a_pasted_picture_is_stored_as_an_asset_and_the_answer_says_so(signed_in):
    document = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    picture = _picture()

    answer = client.patch(
        f"/api/v1/documents/{document['id']}/content",
        json={"added": [{"after": document["elements"][0]["id"], "element": picture}]},
        headers={"If-Match": str(document["revision"])},
    ).json()

    [stored] = answer["changed"]
    assert stored["id"] == picture["id"] and stored["image"]["assetId"] and stored["image"]["src"] == ""
    assert client.get(f"/api/v1/assets/{stored['image']['assetId']}").status_code == 200


def test_saves_one_after_another_are_one_undo_step_as_whole_saves_are(signed_in):
    document = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    first = dict(document["elements"][1], content="Typed once.", inline=[{"text": "Typed once.", "marks": []}])
    second = dict(first, content="Typed twice.", inline=[{"text": "Typed twice.", "marks": []}])
    path = f"/api/v1/documents/{document['id']}/content"

    revision = client.patch(path, json={"changed": [first]}, headers={"If-Match": str(document["revision"])}).json()["revision"]
    client.patch(path, json={"changed": [second]}, headers={"If-Match": str(revision)})
    undone = client.post(f"/api/v1/documents/{document['id']}/undo").json()

    assert [element["content"] for element in undone["elements"]] == [element["content"] for element in document["elements"]]
