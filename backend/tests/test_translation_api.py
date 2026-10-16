"""Translation in use (tracker TRAN-004..007, TRAN-009, TRAN-010): blocks, part of a block, list
items and table cells translated as proposals with their formatting -- nothing changes until
one is accepted, and a block changed meanwhile can't be; a translation that changes a fact is
never proposed and says why; a whole document translated as a new version linked to the
original, which stays as it was, pictures copied, with its report; glossary and language set
on the document; the characters counted against the plan."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.api import deps
from app.api.deps import get_translation_provider
from app.billing.plans import FREE, PLANS
from app.main import app
from app.translation.providers import PseudoTranslator, TranslationUnavailable
from app.translation.service import LABEL
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")
PICTURE = Path(__file__).parent / "fixtures" / "pdf" / "pictures.pdf"


class Recording(PseudoTranslator):
    """The pseudo-translation, remembering what it was asked."""

    def __init__(self, change=None) -> None:
        self.asked: list[tuple[str | None, str, list]] = []
        self.change = change

    async def translate(self, segments, *, source, target, glossary):
        self.asked.append((source, target, [segment.text for segment in segments]))
        answers = await super().translate(segments, source=source, target=target, glossary=glossary)
        return {key: self.change(value) for key, value in answers.items()} if self.change else answers


class Down:
    name = "down"

    async def translate(self, segments, *, source, target, glossary):
        raise TranslationUnavailable("The translation service couldn't be reached.")


@pytest.fixture
def translator():
    return Recording()


@pytest.fixture
def signed_in(api_db, translator, monkeypatch):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 9)
    app.dependency_overrides[get_translation_provider] = lambda: translator
    monkeypatch.setattr(deps, "get_translation_provider", lambda ai: translator)  # the job asks for it itself
    assert client.post("/api/v1/auth/register", json={"email": "translate@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)
    app.dependency_overrides.pop(get_translation_provider, None)


MARKDOWN = (
    "# Dosage guide\n\nTake **5 mg** of the medicine every *morning* with water.\n\n"
    "- Keep it dry.\n- Keep it cool.\n\n| Item | Price |\n| --- | --- |\n| Pen | 1.20 |\n\n```\nprint('kept')\n```"
)


def _create(text: str = MARKDOWN) -> dict:
    response = client.post("/api/v1/documents", json={"text": text})
    assert response.status_code == 201
    return response.json()


def _by_type(document: dict, kind: str) -> dict:
    return next(element for element in document["elements"] if element["type"] == kind)


def _translate(document: dict, ids: list[str], **extra) -> dict:
    response = client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": ids, "targetLanguage": "bg", **extra})
    assert response.status_code == 200, response.text[:400]
    return response.json()


def test_blocks_are_proposed_with_their_formatting_and_accepted_one_by_one(signed_in, translator):
    document = _create()
    heading, paragraph = document["elements"][0], document["elements"][1]
    answer = _translate(document, [heading["id"], paragraph["id"]], sourceLanguage="en")
    assert (answer["proposalCount"], answer["label"], answer["sourceLanguage"]) == (2, LABEL, "en")
    assert answer["characters"] == len("Dosage guide") + len("Take 5 mg of the medicine every morning with water.")
    assert translator.asked[0][:2] == ("en", "bg") and "<m1>5 mg</m1>" in translator.asked[0][2][1]
    saved = answer["document"]
    assert [element["content"] for element in saved["elements"][:2]] == ["Dosage guide", "Take 5 mg of the medicine every morning with water."]
    proposal = next(p for p in saved["proposals"] if p["elementId"] == paragraph["id"])
    assert (proposal["type"], proposal["category"], proposal["source"], proposal["targetLanguage"]) == ("replace_content", "translation", "translation", "bg")
    assert LABEL in proposal["reason"]
    runs = proposal["replacement"]["inline"]
    assert [(run["text"], [mark["type"] for mark in run["marks"]]) for run in runs] == [
        ("Táké ", []), ("5 mg", ["bold"]), (" óf thé médíçíñé évérý ", []), ("mórñíñg", ["italic"]), (" wíth wátér.", []),
    ]

    accepted = client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/accept")
    assert accepted.status_code == 200
    block = next(element for element in accepted.json()["elements"] if element["id"] == paragraph["id"])
    assert block["content"] == "Táké 5 mg óf thé médíçíñé évérý mórñíñg wíth wátér." and block["language"] == "bg"
    assert len(accepted.json()["proposals"]) == 1  # the heading's still waiting
    history = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    assert "Translated a block into Bulgarian (proposal accepted)" in str(history)
    undone = client.post(f"/api/v1/documents/{document['id']}/undo").json()
    assert next(element for element in undone["elements"] if element["id"] == paragraph["id"])["content"].startswith("Take 5 mg")


def test_items_cells_and_part_of_a_block_and_what_isnt_translated(signed_in):
    document = _create()
    listing, table, code = _by_type(document, "list"), _by_type(document, "table"), _by_type(document, "code_block")
    answer = _translate(document, [listing["id"], table["id"], code["id"]])
    proposals = {p["elementId"]: p for p in answer["document"]["proposals"]}
    assert [item["inline"][0]["text"] for item in proposals[listing["id"]]["replacement"]["listItems"]] == ["Kéép ít drý.", "Kéép ít çóól."]
    cells = [[cell["inline"][0]["text"] for cell in row["cells"]] for row in proposals[table["id"]]["replacement"]["table"]["rows"]]
    assert cells == [["Ítém", "Príçé"], ["Péñ", "1.20"]]
    assert code["id"] not in proposals  # code is never translated

    paragraph = document["elements"][1]
    part = _translate(document, [paragraph["id"]], selection={"start": 0, "end": 4})  # "Take"
    replacement = next(p for p in part["document"]["proposals"] if p["elementId"] == paragraph["id"])["replacement"]
    assert replacement["content"] == "Táké 5 mg of the medicine every morning with water."
    assert client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": [paragraph["id"], listing["id"]], "targetLanguage": "bg", "selection": {"start": 0, "end": 4}}).status_code == 422
    assert client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": ["nope"], "targetLanguage": "bg"}).status_code == 422
    assert client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": [listing["id"]], "targetLanguage": "bg", "selection": {"start": 0, "end": 4}}).status_code == 422


def test_a_translation_that_changes_a_fact_is_never_proposed(signed_in, translator):
    translator.change = lambda text: text.replace("5", "50")
    document = _create()
    paragraph = document["elements"][1]
    answer = _translate(document, [paragraph["id"]])
    assert answer["proposalCount"] == 0
    assert answer["notTranslated"] == [{"elementId": paragraph["id"], "reasons": ["Bulgarian: a number differs from the original"]}]
    assert answer["document"]["proposals"] == []


def test_a_block_changed_since_it_was_translated_cant_take_the_translation(signed_in):
    document = _create()
    paragraph = document["elements"][1]
    saved = _translate(document, [paragraph["id"]])["document"]
    proposal = saved["proposals"][0]
    elements = saved["elements"]
    elements[1] = dict(elements[1], content="Something else.", inline=[{"text": "Something else.", "marks": []}])
    assert client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements}).status_code == 200
    refused = client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/accept")
    assert (refused.status_code, refused.json()["code"]) == (409, "stale_proposal")


def test_the_glossary_is_the_documents_and_locked_terms_hold(signed_in, translator):
    document = _create("Give the patient Aspirin with water every morning.")
    terms = [{"source": "Aspirin", "target": "Аспирин", "domain": "medical", "locked": True}]
    set_ = client.put(f"/api/v1/documents/{document['id']}/glossary", json={"terms": terms})
    assert set_.status_code == 200 and set_.json()["glossary"][0]["target"] == "Аспирин"
    element = document["elements"][0]
    answer = _translate(document, [element["id"]])
    assert "Аспирин" in answer["document"]["proposals"][0]["after"]
    translator.change = lambda text: text.replace("Аспирин", "лекарството")
    assert _translate(document, [element["id"]])["notTranslated"][0]["reasons"] == ["Bulgarian: a locked glossary term wasn't translated as the glossary says"]
    # Limited to other languages, the term isn't the glossary's for this translation.
    client.put(f"/api/v1/documents/{document['id']}/glossary", json={"terms": [dict(terms[0], targetLanguage="de")]})
    assert _translate(document, [element["id"]])["proposalCount"] == 1


def test_the_language_is_detected_and_can_be_set(signed_in, translator):
    english = _create("The patient should take the tablet with water and not with milk.")
    assert client.get(f"/api/v1/documents/{english['id']}/language").json() == {
        "set": None, "detected": "en", "script": "Latn", "direction": "ltr", "confidence": 0.95, "name": "English",
    }
    _translate(english, [english["elements"][0]["id"]])
    assert translator.asked[-1][0] == "en"  # detected, since none was said
    client.put(f"/api/v1/documents/{english['id']}/language", json={"language": "en-GB"})
    language = client.get(f"/api/v1/documents/{english['id']}/language").json()
    assert (language["set"], language["name"]) == ("en-GB", "English")
    assert client.put(f"/api/v1/documents/{english['id']}/language", json={"language": "not a tag!"}).status_code == 422


def test_characters_are_counted_and_the_plan_holds(signed_in, monkeypatch):
    document = _create()
    paragraph = document["elements"][1]
    characters = _translate(document, [paragraph["id"]])["characters"]
    usage = {unit["key"]: unit for unit in client.get("/api/v1/usage").json()["units"]}
    assert usage["translationCharacters"]["used"] == characters
    free = PLANS[FREE]
    monkeypatch.setitem(PLANS, FREE, free.model_copy(update={"entitlements": free.entitlements.model_copy(update={"maxTranslationCharacters": characters + 5})}))
    refused = client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": [paragraph["id"]], "targetLanguage": "bg"})
    assert (refused.status_code, refused.json()["code"], refused.json()["details"]["entitlement"]) == (402, "plan_limit", "maxTranslationCharacters")


def test_an_unreachable_service_is_said(signed_in):
    app.dependency_overrides[get_translation_provider] = lambda: Down()
    document = _create()
    refused = client.post(f"/api/v1/documents/{document['id']}/translate", json={"elementIds": [document["elements"][1]["id"]], "targetLanguage": "bg"})
    assert (refused.status_code, refused.json()["code"]) == (503, "translation_unavailable")
    usage = {unit["key"]: unit for unit in client.get("/api/v1/usage").json()["units"]}
    assert usage["translationCharacters"]["used"] == 0  # given back: nothing was translated


def test_a_whole_document_becomes_a_translated_version_and_the_original_stays(signed_in):
    uploaded = client.post("/api/v1/documents/upload", files={"file": ("pictures.pdf", PICTURE.read_bytes(), "application/pdf")}).json()
    before = client.get(f"/api/v1/documents/{uploaded['id']}").json()
    job = client.post("/api/v1/jobs/translate-document", json={"documentId": uploaded["id"], "targetLanguage": "bg", "sourceLanguage": "en"}).json()
    assert job["status"] == "succeeded", job
    version = client.get(f"/api/v1/documents/{job['result']['documentId']}").json()
    assert version["id"] != uploaded["id"] and version["metadata"]["title"] == f"{before['metadata']['title']} (Bulgarian)"
    origin = version["metadata"]["translatedFrom"]
    assert (origin["documentId"], origin["revision"], origin["sourceLanguage"], origin["targetLanguage"], origin["provider"]) == (
        uploaded["id"], before["revision"], "en", "bg", "pseudo",
    )
    assert (version["metadata"]["language"], version["metadata"]["sourceType"]) == ("bg", "translation")
    texts = [element["content"] for element in version["elements"] if element["type"] != "image"]
    assert texts == ["Píçtúréš Twó píçtúréš fóllów thíš líñé.", "Á çáptíóñ úñdér thé píçtúréš."]
    # Its pictures are its own copies: the original's are untouched.
    old = [element["image"]["assetId"] for element in before["elements"] if element["type"] == "image"]
    new = [element["image"]["assetId"] for element in version["elements"] if element["type"] == "image"]
    assert len(new) == len(old) == 2 and not set(new) & set(old) and all(new)
    report = version["importReport"]
    assert report["stage"] == "translation" and report["items"][0]["feature"] == "translation.ai_assisted" and LABEL in report["items"][0]["reason"]
    assert client.get(f"/api/v1/documents/{uploaded['id']}").json()["elements"] == before["elements"]  # the original as it was
    history = client.get(f"/api/v1/documents/{version['id']}/versions").json()
    assert "Translated from" in str(history) and "into Bulgarian" in str(history)
