import pytest

from app.db.models import User, Workspace, WorkspaceMember
from app.models.document import Document, DocumentMetadata, Element, ElementType, InlineRun, Mark, MarkType
from app.repositories.document_repository import DocumentRepository


async def _make_workspace(db_session, slug="acme") -> str:
    workspace = Workspace(name="Acme", slug=slug)
    db_session.add(workspace)
    await db_session.flush()
    return workspace.id


def _rich_document() -> Document:
    return Document(
        metadata=DocumentMetadata(title="Договор за наем"),
        elements=[
            Element(
                type=ElementType.HEADING,
                content="Заглавие",
                inline=[InlineRun(text="Заглавие", marks=[Mark(type=MarkType.BOLD)])],
                order=0,
                level=1,
                confidence=1.0,
            )
        ],
        unsupportedFeatures=["Merged table cells were flattened -- original colspan/rowspan not preserved."],
    )


async def test_create_then_get_round_trips_unicode_enums_and_datetimes(db_session):
    workspace_id = await _make_workspace(db_session)
    repo = DocumentRepository(db_session)
    document = _rich_document()

    await repo.create(workspace_id, document)
    await db_session.commit()
    # Without this, get() is served from the identity map and never reads the JSON column back.
    db_session.expunge_all()

    fetched = await repo.get(document.id)
    assert fetched is not None
    assert fetched.metadata.title == "Договор за наем"
    assert fetched.elements[0].inline[0].marks[0].type == MarkType.BOLD
    assert fetched.metadata.createdAt == document.metadata.createdAt
    assert fetched.unsupportedFeatures == document.unsupportedFeatures


async def test_get_unknown_document_returns_none(db_session):
    repo = DocumentRepository(db_session)
    assert await repo.get("does-not-exist") is None


async def test_update_persists_changes(db_session):
    workspace_id = await _make_workspace(db_session)
    repo = DocumentRepository(db_session)
    document = _rich_document()
    await repo.create(workspace_id, document)
    await db_session.commit()

    document.metadata.title = "Renamed"
    updated = await repo.update(document)
    await db_session.commit()
    db_session.expunge_all()

    assert updated is True
    fetched = await repo.get(document.id)
    assert fetched.metadata.title == "Renamed"


async def test_update_unknown_document_returns_false(db_session):
    repo = DocumentRepository(db_session)
    assert await repo.update(_rich_document()) is False


async def test_delete_removes_document_and_reports_success(db_session):
    workspace_id = await _make_workspace(db_session)
    repo = DocumentRepository(db_session)
    document = _rich_document()
    await repo.create(workspace_id, document)
    await db_session.commit()

    assert await repo.delete(document.id) is True
    await db_session.commit()
    db_session.expunge_all()
    assert await repo.get(document.id) is None


async def test_delete_unknown_document_returns_false(db_session):
    repo = DocumentRepository(db_session)
    assert await repo.delete("does-not-exist") is False


async def test_document_formatted_with_a_code_defined_template_can_be_saved(db_session):
    # Built-in/custom template ids aren't `templates` rows until Phase 7 moves templates
    # into the DB, so they must not reach the documents.template_id foreign key.
    workspace_id = await _make_workspace(db_session)
    repo = DocumentRepository(db_session)
    document = _rich_document()
    document.templateId = "academic-default"

    await repo.create(workspace_id, document)
    document.templateId = "professional-cv"
    await repo.update(document)
    await db_session.commit()
    db_session.expunge_all()

    assert (await repo.get(document.id)).templateId == "professional-cv"


async def test_get_for_user_only_returns_documents_in_that_users_workspaces(db_session):
    member_workspace = await _make_workspace(db_session, slug="mine")
    other_workspace = await _make_workspace(db_session, slug="theirs")
    user = User(email="member@example.com", hashed_password="x")
    db_session.add_all([user, WorkspaceMember(workspace_id=member_workspace, user=user)])
    repo = DocumentRepository(db_session)
    mine, theirs = _rich_document(), _rich_document()
    await repo.create(member_workspace, mine)
    await repo.create(other_workspace, theirs)
    await db_session.commit()

    assert (await repo.get_for_user(mine.id, user.id)).id == mine.id
    assert await repo.get_for_user(theirs.id, user.id) is None


async def test_list_for_workspace_only_returns_that_workspaces_documents(db_session):
    workspace_a = await _make_workspace(db_session, slug="a")
    workspace_b = await _make_workspace(db_session, slug="b")
    repo = DocumentRepository(db_session)
    doc_a = _rich_document()
    doc_b = _rich_document()
    await repo.create(workspace_a, doc_a)
    await repo.create(workspace_b, doc_b)
    await db_session.commit()

    only_a = await repo.list_for_workspace(workspace_a)
    assert [d.id for d in only_a] == [doc_a.id]
