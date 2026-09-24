import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Document,
    DocumentVersion,
    Template,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)


async def _make_user_and_workspace(db_session, email="owner@example.com"):
    user = User(email=email, hashed_password="hashed")
    workspace = Workspace(name="Acme", slug=f"acme-{email}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    return user, workspace


async def test_user_round_trips_with_defaults(db_session):
    user = User(email="a@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.commit()

    fetched = (await db_session.execute(select(User).where(User.email == "a@example.com"))).scalar_one()
    assert fetched.is_active is True
    assert fetched.full_name is None
    assert fetched.created_at is not None
    assert fetched.id != ""


async def test_workspace_member_relationship_round_trips(db_session):
    user, workspace = await _make_user_and_workspace(db_session)
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER.value)
    db_session.add(member)
    await db_session.commit()

    fetched = (await db_session.execute(select(WorkspaceMember))).scalar_one()
    assert fetched.role == "owner"
    await db_session.refresh(fetched, attribute_names=["workspace", "user"])
    assert fetched.workspace.slug == workspace.slug
    assert fetched.user.email == user.email


async def test_duplicate_workspace_membership_is_rejected(db_session):
    user, workspace = await _make_user_and_workspace(db_session)
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await db_session.commit()

    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_workspace_member_with_unknown_workspace_is_rejected(db_session):
    user, _ = await _make_user_and_workspace(db_session)
    db_session.add(WorkspaceMember(workspace_id="does-not-exist", user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_deleting_workspace_cascades_to_members(db_session):
    user, workspace = await _make_user_and_workspace(db_session)
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await db_session.commit()

    await db_session.delete(workspace)
    await db_session.commit()

    remaining = (await db_session.execute(select(WorkspaceMember))).scalars().all()
    assert remaining == []


async def test_document_json_data_round_trips_nested_structures(db_session):
    _, workspace = await _make_user_and_workspace(db_session)
    payload = {"elements": [{"type": "heading", "inline": [{"text": "Hi", "marks": ["bold"]}]}], "schemaVersion": 1}
    document = Document(workspace_id=workspace.id, title="My Doc", data=payload)
    db_session.add(document)
    await db_session.commit()

    fetched = (await db_session.execute(select(Document).where(Document.title == "My Doc"))).scalar_one()
    assert fetched.data == payload
    assert fetched.schema_version == 1
    assert fetched.document_type == "general"


async def test_document_version_unique_per_document_and_revision(db_session):
    _, workspace = await _make_user_and_workspace(db_session)
    document = Document(workspace_id=workspace.id, title="Doc", data={})
    db_session.add(document)
    await db_session.flush()

    db_session.add(DocumentVersion(document_id=document.id, revision_number=1, data={}))
    await db_session.commit()

    db_session.add(DocumentVersion(document_id=document.id, revision_number=1, data={}))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_builtin_template_has_no_workspace(db_session):
    template = Template(workspace_id=None, name="Business Letter", is_builtin=True)
    db_session.add(template)
    await db_session.commit()

    fetched = (await db_session.execute(select(Template))).scalar_one()
    assert fetched.workspace_id is None
    assert fetched.is_builtin is True
