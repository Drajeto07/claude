"""Translation's edges (TRAN-005): what isn't translated is named -- a block holding Word content
placed by its text, blocks nested in a quote -- and a block translated again has one
translation waiting, the newest."""

import pytest
from fastapi.testclient import TestClient

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.api.deps import get_translation_provider
from app.formatting.proposals import accept
from app.main import app
from app.models.document import ChangeCategory, Document, Element, ElementLayout, ElementType, InlineRun, ProposedChange
from app.translation.providers import PseudoTranslator
from app.translation.service import PRESERVED, UNTRANSLATABLE, collect
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")


def test_word_content_placed_by_the_text_and_nested_blocks_are_named_not_translated():
    paragraph = Element(type=ElementType.PARAGRAPH, content="See the field.", inline=[InlineRun(text="See the field.")], order=0)
    with_field = paragraph.model_copy(update={"id": "f", "preservedAttributes": {"ooxml": [{"kind": "field", "at": 4}]}})
    quote = Element(type=ElementType.QUOTE, content="Quoted.", order=1, children=[paragraph.model_copy(update={"id": "inner"})])
    plain = paragraph.model_copy(update={"id": "plain"})
    translation = collect([with_field, quote, plain])
    assert translation.skipped == {"f": PRESERVED, quote.id: UNTRANSLATABLE}
    assert [segment.element_id for segment in translation.segments] == ["plain"]


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 9)
    app.dependency_overrides[get_translation_provider] = lambda: PseudoTranslator()
    assert client.post("/api/v1/auth/register", json={"email": "edges@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)
    app.dependency_overrides.pop(get_translation_provider, None)


def test_a_block_translated_again_has_one_translation_waiting(signed_in):
    document = client.post("/api/v1/documents", json={"text": "# Title\n\nKeep the tablets dry."}).json()
    paragraph = document["elements"][1]["id"]
    for target in ("bg", "de"):
        answer = client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": [paragraph], "targetLanguage": target})
        assert answer.status_code == 200
    waiting = answer.json()["document"]["proposals"]
    assert [(proposal["elementId"], proposal["targetLanguage"]) for proposal in waiting] == [(paragraph, "de")]


def test_accepting_keeps_the_blocks_place_style_and_provenance_as_they_are_now():
    """What changed about the block since it was translated -- its style, its place, where it
    came from -- isn't undone by the translation: only its text and formatting are the translation's."""
    current = Element(
        type=ElementType.PARAGRAPH, content="Keep it dry.", inline=[InlineRun(text="Keep it dry.")], order=3, styleRef="Quote style",
        layout=ElementLayout(page=2, x=1, y=2, width=3, height=4), sourceBlocks=[7],
    )
    stale = current.model_copy(update={"order": 0, "styleRef": "Old style", "layout": None, "sourceBlocks": None})
    replacement = stale.model_copy(update={"content": "Pazete go suho.", "inline": [InlineRun(text="Pazete go suho.")], "language": "bg"})
    proposal = ProposedChange(
        type="replace_content", category=ChangeCategory.TRANSLATION, source="translation", elementId=current.id,
        before=current.content, after=replacement.content, replacement=replacement, targetLanguage="bg",
    )
    document = Document(elements=[current], proposals=[proposal])
    accept(document, proposal.id)
    (block,) = document.elements
    assert (block.id, block.content, block.language) == (current.id, "Pazete go suho.", "bg")
    assert (block.order, block.styleRef, block.layout, block.sourceBlocks) == (3, "Quote style", current.layout, [7])
    assert document.proposals == []
