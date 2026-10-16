"""Review Changes as one layer (tracker REV-002/003, brief §58 and §89): every change the user
didn't make -- an AI instruction's, a translation, a health fix -- waits as a proposal with its
category; changes to the content need the user's explicit acceptance, enforced on the server:
nothing but accepting a proposal can insert, delete or move content, a whole category can be
accepted at once only when it isn't the content's, and even then nothing that changes the
words goes in with it."""

import pytest
from fastapi.testclient import TestClient

from app.ai.factory import get_ai_provider
from app.ai.base import AIStructuredOutputError
from app.ai.schemas import AIDocumentOperation, AIInstructionExtractionResponse
from app.api import deps
from app.formatting.engine import UnacceptedContentChangeError, apply_operations, recompute_styles
from app.formatting.health_fixes import fixes
from app.formatting.proposals import ContentNeedsReviewError, accept_category, changes_text
from app.main import app
from app.models.document import ChangeCategory, Document, Element, ElementType, InlineRun, ProposedChange
from app.api.deps import get_translation_provider
from app.translation.providers import PseudoTranslator
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")


def _paragraph(text: str) -> Element:
    return Element(type=ElementType.PARAGRAPH, content=text, inline=[InlineRun(text=text)] if text else None, order=0)


def _doc(*elements: Element) -> Document:
    for index, element in enumerate(elements):
        element.order = index
    document = Document(elements=list(elements))
    recompute_styles(document)
    return document


# --- REV-003: enforced on the server ------------------------------------------------------------


@pytest.mark.parametrize(
    "operation",
    [
        AIDocumentOperation(op="delete_element", element_id="a"),
        AIDocumentOperation(op="insert_element", element_type="paragraph", text="Added."),
        AIDocumentOperation(op="move_element", element_id="a", after_element_id=None),
    ],
)
def test_nothing_but_an_accepted_proposal_can_change_the_content(operation):
    first = _paragraph("Kept as it is.")
    first.id = "a"
    document = _doc(first, _paragraph("And this."))
    with pytest.raises(UnacceptedContentChangeError):
        apply_operations(document, [operation])
    assert [element.content for element in document.elements] == ["Kept as it is.", "And this."]
    apply_operations(document, [AIDocumentOperation(op="set_style", element_id="a", property="bold", value="true")])  # formatting: fine


def test_a_whole_category_never_takes_the_content_or_a_change_to_the_words():
    blank, words = _paragraph(""), _paragraph("A paragraph with words in it.")
    document = _doc(_paragraph("Some text before."), blank, words)
    [empty_fix] = fixes(document, ["empty_paragraphs"])
    slipped = ProposedChange(type="delete_element", category=ChangeCategory.STRUCTURE, elementId=words.id, before=words.content)
    content = ProposedChange(type="delete_element", category=ChangeCategory.CONTENT, elementId=words.id, before=words.content)
    document.proposals = [empty_fix, slipped, content]

    with pytest.raises(ContentNeedsReviewError):
        accept_category(document, ChangeCategory.CONTENT)
    assert changes_text(document, slipped) and not changes_text(document, empty_fix)
    reworded = words.model_copy(update={"content": "Other words entirely.", "inline": [InlineRun(text="Other words entirely.")]})
    restyled = words.model_copy(update={"content": "A paragraph  with words in it."})
    as_format = ProposedChange(type="replace_content", category=ChangeCategory.FORMAT, elementId=words.id, replacement=reworded)
    assert changes_text(document, as_format)
    assert not changes_text(document, as_format.model_copy(update={"replacement": restyled}))  # spacing aside, the same words
    accepted, skipped = accept_category(document, ChangeCategory.STRUCTURE)

    assert [proposal.id for proposal in accepted] == [empty_fix.id] and [proposal.id for proposal in skipped] == [slipped.id]
    assert [element.content for element in document.elements] == ["Some text before.", "A paragraph with words in it."]
    assert {proposal.id for proposal in document.proposals} == {slipped.id, content.id}  # left to be accepted one by one


@pytest.fixture
def signed_in(api_db, monkeypatch):
    client.cookies.clear()
    translator = PseudoTranslator()
    app.dependency_overrides[get_translation_provider] = lambda: translator
    monkeypatch.setattr(deps, "get_translation_provider", lambda ai: translator)
    assert client.post("/api/v1/auth/register", json={"email": "review@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)
    app.dependency_overrides.pop(get_translation_provider, None)


def _words(document: dict) -> list[str]:
    return [element["content"] for element in document["elements"]]


def test_every_kind_of_change_waits_with_its_category_and_the_words_stay(signed_in):
    document = client.post("/api/v1/documents", json={"text": "# Report\n\nThe first paragraph here.\n\n### Deep heading\n\nThe last paragraph here."}).json()
    heading, first, deep, last = (element["id"] for element in document["elements"])

    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIInstructionExtractionResponse(operations=[AIDocumentOperation(op="delete_element", element_id=last)])])
    client.post(f"/api/v1/documents/{document['id']}/format", data={"instructionsText": "drop the last paragraph"})
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 9)
    client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": [first], "targetLanguage": "bg", "sourceLanguage": "en"})
    saved = client.post(f"/api/v1/documents/{document['id']}/health/fixes", json={"checkIds": ["hierarchy"]}).json()["document"]

    assert {(proposal["source"], proposal["category"]) for proposal in saved["proposals"]} == {
        ("instruction", "content"),
        ("translation", "translation"),
        ("health", "structure"),
    }
    assert _words(saved) == _words(document)  # nothing applied until accepted
    assert next(element for element in saved["elements"] if element["id"] == deep)["level"] == 3

    refused = client.post(f"/api/v1/documents/{document['id']}/proposals/accept", json={"category": "content"})
    assert refused.status_code == 422 and refused.json()["code"] == "content_needs_review"

    structure = client.post(f"/api/v1/documents/{document['id']}/proposals/accept", json={"category": "structure"}).json()
    assert (structure["accepted"], structure["skipped"]) == (1, 0)
    assert next(element for element in structure["document"]["elements"] if element["id"] == deep)["level"] == 2

    translated = client.post(f"/api/v1/documents/{document['id']}/proposals/accept", json={"category": "translation"}).json()
    assert translated["accepted"] == 1 and _words(translated["document"])[1] != "The first paragraph here."
    assert [proposal["source"] for proposal in translated["document"]["proposals"]] == ["instruction"]  # the content's waits

    undone = client.post(f"/api/v1/documents/{document['id']}/undo").json()  # one step per category accepted
    assert _words(undone)[1] == "The first paragraph here."
    assert next(element for element in undone["elements"] if element["id"] == deep)["level"] == 2
