"""What an AI instruction asks for is sorted by what it touches (tracker AI-005):
formatting applies at once, but inserting, deleting or moving content becomes a
proposal the user accepts or rejects first (AI-006, brief §19: PLAN -> VALIDATE
-> PREVIEW -> ACCEPT -> APPLY). Nothing is deleted silently."""

import pytest
from fastapi.testclient import TestClient

from app.ai.factory import get_ai_provider
from app.ai.schemas import AIDocumentOperation, AIInstructionExtractionResponse
from app.formatting.proposals import StaleProposalError, accept, classify, split_operations
from app.main import app
from app.models.document import ChangeCategory, Document, Element, ElementType, InlineRun, ProposedChange
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")


@pytest.fixture
def document(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "proposals@example.com", "password": "long enough password"}).status_code == 201
    yield client.post("/api/v1/documents", json={"text": "# Report\n\nThe first paragraph.\n\nThe second paragraph.\n\nThe third paragraph."}).json()
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _instruct(document: dict, *operations: AIDocumentOperation, text: str = "tidy this up") -> dict:
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIInstructionExtractionResponse(operations=list(operations))])
    response = client.post(f"/api/v1/documents/{document['id']}/format", data={"instructionsText": text})
    assert response.status_code == 200, response.text
    return response.json()


def _texts(body: dict) -> list[str]:
    return [element["content"] for element in body["elements"]]


def test_operations_are_sorted_by_what_they_touch():
    operations = [
        AIDocumentOperation(op="set_style", element_id="a", property="bold", value="true"),
        AIDocumentOperation(op="add_page_break", after_element_id="a"),
        AIDocumentOperation(op="delete_element", element_id="a"),
        AIDocumentOperation(op="insert_element", element_type="paragraph", text="x"),
        AIDocumentOperation(op="move_element", element_id="a", after_element_id="b"),
    ]

    assert [classify(operation) for operation in operations] == [
        ChangeCategory.FORMAT,
        ChangeCategory.STRUCTURE,
        ChangeCategory.CONTENT,
        ChangeCategory.CONTENT,
        ChangeCategory.CONTENT,
    ]
    now, proposed = split_operations(operations)
    assert [operation.op for operation in now] == ["set_style", "add_page_break"]
    assert [operation.op for operation in proposed] == ["delete_element", "insert_element", "move_element"]


def test_content_changes_wait_for_review_while_formatting_applies(document):
    heading, first, second, third = (element["id"] for element in document["elements"])

    body = _instruct(
        document,
        AIDocumentOperation(op="set_style", element_id=heading, property="color", value="red"),
        AIDocumentOperation(op="delete_element", element_id=second),
        AIDocumentOperation(op="insert_element", after_element_id=first, element_type="paragraph", text="An added paragraph."),
        AIDocumentOperation(op="move_element", element_id=third, after_element_id=heading),
        text="make the title red, drop the second paragraph, add one, move the last up",
    )

    assert (body["instructionEditCount"], body["proposalCount"]) == (1, 3)
    saved = body["document"]
    assert saved["resolvedStyles"][heading]["color"] == "red"  # formatting: applied
    assert _texts(saved) == _texts(document)  # content: untouched
    proposals = {proposal["type"]: proposal for proposal in saved["proposals"]}
    assert proposals["delete_element"]["before"] == "The second paragraph."
    assert proposals["insert_element"]["after"] == "An added paragraph."
    assert proposals["move_element"]["before"] == "The third paragraph."
    assert all(proposal["category"] == "content" and proposal["reason"].startswith("make the title red") for proposal in saved["proposals"])


def test_accepting_applies_the_change_as_one_undoable_step(document):
    second = document["elements"][2]["id"]
    proposal = _instruct(document, AIDocumentOperation(op="delete_element", element_id=second))["document"]["proposals"][0]

    accepted = client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/accept")

    assert accepted.status_code == 200
    body = accepted.json()
    assert _texts(body) == ["Report", "The first paragraph.", "The third paragraph."]
    assert body["proposals"] == []
    history = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    assert any("AI proposal accepted" in version["description"] for version in history)
    undone = client.post(f"/api/v1/documents/{document['id']}/undo").json()
    assert "The second paragraph." in _texts(undone)


def test_rejecting_changes_nothing(document):
    second = document["elements"][2]["id"]
    proposal = _instruct(document, AIDocumentOperation(op="delete_element", element_id=second))["document"]["proposals"][0]

    rejected = client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/reject").json()

    assert _texts(rejected) == _texts(document)
    assert rejected["proposals"] == []
    assert client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/accept").status_code == 404


def test_proposals_about_content_that_is_gone_are_dropped(document):
    heading, first, second, third = (element["id"] for element in document["elements"])
    saved = _instruct(
        document,
        AIDocumentOperation(op="delete_element", element_id=second),
        AIDocumentOperation(op="delete_element", element_id=third),
        AIDocumentOperation(op="move_element", element_id=third, after_element_id=heading),
    )["document"]
    by_type = {(proposal["type"], proposal["elementId"]): proposal["id"] for proposal in saved["proposals"]}

    # The user deletes the second paragraph themselves: the proposal to delete it goes.
    kept = [element for element in saved["elements"] if element["id"] != second]
    typed = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": kept}).json()
    assert {(proposal["type"], proposal["elementId"]) for proposal in typed["proposals"]} == {("delete_element", third), ("move_element", third)}

    # Accepting "delete the third" makes "move the third" moot: it goes too.
    accepted = client.post(f"/api/v1/documents/{document['id']}/proposals/{by_type[('delete_element', third)]}/accept").json()
    assert accepted["proposals"] == []


def test_a_proposal_that_no_longer_fits_is_refused_not_applied_elsewhere():
    document = Document(elements=[Element(type=ElementType.PARAGRAPH, content="Kept.", inline=[InlineRun(text="Kept.")], order=0)])
    document.proposals = [ProposedChange(type="move_element", elementId="gone", afterElementId=None, before="Gone.")]

    with pytest.raises(StaleProposalError):
        accept(document, document.proposals[0].id)
    assert [element.content for element in document.elements] == ["Kept."]


def test_the_same_proposal_isnt_stacked(document):
    second = document["elements"][2]["id"]
    _instruct(document, AIDocumentOperation(op="delete_element", element_id=second))
    again = _instruct(document, AIDocumentOperation(op="delete_element", element_id=second))

    assert again["proposalCount"] == 0
    assert len(again["document"]["proposals"]) == 1


def test_a_style_an_instruction_sets_on_one_element_is_kept(document):
    """Regression: the formatting pass rebuilt the rules after the operations and
    dropped a style an instruction set on one element -- "Applied 1 change", nothing changed."""
    heading = document["elements"][0]["id"]

    body = _instruct(document, AIDocumentOperation(op="set_style", element_id=heading, property="color", value="red"), text="make the title red")

    assert body["instructionEditCount"] == 1
    assert body["document"]["resolvedStyles"][heading]["color"] == "red"
