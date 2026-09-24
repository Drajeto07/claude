"""Who can see and change which template, with more than one person in a
workspace. There's no invite flow yet, so the second member is added directly."""

import pytest
import pytest_asyncio

from app.db.models import TemplateVisibility, WorkspaceMember, WorkspaceRole
from app.formatting.style_system import StyleSystem
from app.formatting.templates import UnknownTemplateError
from app.services.auth_service import AuthService
from app.services.template_service import (
    TemplateNotFoundError,
    TemplateNotSharedError,
    TemplateReadOnlyError,
    TemplateService,
)

_STYLE = StyleSystem.model_validate({"paragraph": {"fontFamily": "Georgia"}})


@pytest_asyncio.fixture
async def team(db_session):
    """(owner service, member service, the owner's workspace id) -- both
    services act inside the owner's workspace."""
    auth = AuthService(db_session)
    owner = await auth.register("owner@example.com", "long enough password", None)
    member = await auth.register("member@example.com", "long enough password", "Member")
    workspace_id = await auth.default_workspace_id(owner.id)
    db_session.add(WorkspaceMember(workspace_id=workspace_id, user_id=member.id, role=WorkspaceRole.MEMBER.value))
    await db_session.commit()

    owner_templates = TemplateService(db_session, user_id=owner.id)
    member_templates = TemplateService(db_session, user_id=member.id)
    member_templates._workspace_id = workspace_id  # as a workspace switcher would
    return owner_templates, member_templates, workspace_id


async def _make(service, name, visibility=TemplateVisibility.WORKSPACE, workspace_id=None):
    return await service.create(
        name=name, category="general", description="", style_system=_STYLE, visibility=visibility, workspace_id=workspace_id
    )


async def test_shared_templates_are_visible_to_members_private_ones_only_to_their_creator(team):
    owner, member, _ = team
    shared = await _make(owner, "Shared")
    private = await _make(owner, "Mine", TemplateVisibility.PRIVATE)

    visible = {view.id for view in await member.list_visible()}
    assert shared.id in visible and private.id not in visible
    with pytest.raises(TemplateNotFoundError):
        await member.get(private.id)
    with pytest.raises(UnknownTemplateError):
        await member.rules_for(private.id)
    assert (await member.rules_for(shared.id))[0].value == "Georgia"


async def test_a_member_cannot_change_someone_elses_template(team):
    owner, member, _ = team
    template = await _make(owner, "Owner's")

    assert (await member.get(template.id)).editable is False
    with pytest.raises(TemplateReadOnlyError):
        await member.update(template.id, expected_version=None, name="Mine now")
    with pytest.raises(TemplateReadOnlyError):
        await member.delete(template.id)


async def test_the_owner_can_change_a_members_template(team):
    owner, member, workspace_id = team
    template = await _make(member, "Member's", workspace_id=workspace_id)

    assert (await owner.get(template.id)).editable is True
    renamed = await owner.update(template.id, expected_version=None, name="Tidied up")
    assert renamed.name == "Tidied up"
    await owner.delete(template.id)
    with pytest.raises(TemplateNotFoundError):
        await member.get(template.id)


async def test_only_the_creator_decides_who_sees_a_template(team):
    owner, member, workspace_id = team
    template = await _make(member, "Member's", workspace_id=workspace_id)

    with pytest.raises(TemplateReadOnlyError):
        await owner.update(template.id, expected_version=None, visibility=TemplateVisibility.PRIVATE)


async def test_only_the_workspace_owner_sets_its_default(team):
    owner, member, _ = team
    with pytest.raises(TemplateReadOnlyError):
        await member.set_default("academic-default")
    await owner.set_default("academic-default")
    assert await member.default_template_id() == "academic-default"


async def test_a_private_template_cannot_be_the_workspace_default(team):
    owner, _, _ = team
    private = await _make(owner, "Mine", TemplateVisibility.PRIVATE)

    with pytest.raises(TemplateNotSharedError):
        await owner.set_default(private.id)


async def test_making_the_default_template_private_unsets_it(team):
    owner, member, _ = team
    template = await _make(owner, "House style")
    await owner.set_default(template.id)

    await owner.update(template.id, expected_version=None, visibility=TemplateVisibility.PRIVATE)

    assert await owner.default_template_id() is None
    assert await member.default_template_id() is None
