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


async def test_every_stored_template_belongs_to_a_workspace(db_session):
    # Built-ins are code (formatting/builtin_templates.json), never rows.
    db_session.add(Template(workspace_id=None, name="Orphan", style_system={}, rules=[]))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_template_version_counts_up_on_every_save(db_session):
    _, workspace = await _make_user_and_workspace(db_session)
    template = Template(workspace_id=workspace.id, name="House style", style_system={}, rules=[])
    db_session.add(template)
    await db_session.commit()
    assert (template.version, template.visibility) == (1, "workspace")

    template.name = "House style v2"
    await db_session.commit()
    assert template.version == 2


async def test_deleting_a_source_document_keeps_the_template(db_session):
    _, workspace = await _make_user_and_workspace(db_session)
    document = Document(workspace_id=workspace.id, title="Thesis", data={})
    db_session.add(document)
    await db_session.flush()
    template = Template(workspace_id=workspace.id, name="From thesis", style_system={}, rules=[], source_document_id=document.id)
    db_session.add(template)
    await db_session.commit()

    await db_session.delete(document)
    await db_session.commit()
    await db_session.refresh(template)

    assert template.source_document_id is None
