from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Template as TemplateRow
from app.db.models import TemplateVersion, TemplateVisibility, User, Workspace, WorkspaceMember


class TemplateRepository:
    """Queries for workspace-owned templates. "Visible" means: in a workspace
    the user belongs to, and either shared with that workspace or their own.
    Rows come back with the user's role in the owning workspace, which is what
    decides whether they may change them."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _visible_to(self, user_id: str):
        return (
            select(TemplateRow, WorkspaceMember.role)
            .join(
                WorkspaceMember,
                and_(WorkspaceMember.workspace_id == TemplateRow.workspace_id, WorkspaceMember.user_id == user_id),
            )
            .where(
                or_(TemplateRow.visibility == TemplateVisibility.WORKSPACE.value, TemplateRow.created_by == user_id)
            )
        )

    async def list_visible(self, user_id: str) -> list[tuple[TemplateRow, str]]:
        result = await self._session.execute(
            self._visible_to(user_id).order_by(func.lower(TemplateRow.name), TemplateRow.created_at)
        )
        return [(row, role) for row, role in result.all()]

    async def get_visible(self, template_id: str, user_id: str) -> tuple[TemplateRow, str] | None:
        """None both when the template doesn't exist and when the user can't
        see it, so callers can't tell the two apart."""
        found = (await self._session.execute(self._visible_to(user_id).where(TemplateRow.id == template_id))).first()
        return (found[0], found[1]) if found else None

    def add(self, row: TemplateRow) -> None:
        self._session.add(row)

    async def delete(self, row: TemplateRow) -> None:
        await self._session.delete(row)

    async def versions(self, template_id: str) -> list[tuple[TemplateVersion, str | None]]:
        """Newest first, each with who saved it (name, else email; None once
        that account is gone)."""
        result = await self._session.execute(
            select(TemplateVersion, func.coalesce(User.full_name, User.email))
            .outerjoin(User, User.id == TemplateVersion.created_by)
            .where(TemplateVersion.template_id == template_id)
            .order_by(TemplateVersion.version_number.desc())
        )
        return [(version, author) for version, author in result.all()]

    async def version(self, template_id: str, number: int) -> TemplateVersion | None:
        return (
            await self._session.execute(
                select(TemplateVersion).where(
                    TemplateVersion.template_id == template_id, TemplateVersion.version_number == number
                )
            )
        ).scalar_one_or_none()

    async def drop_versions_up_to(self, template_id: str, number: int) -> None:
        await self._session.execute(
            delete(TemplateVersion).where(
                TemplateVersion.template_id == template_id, TemplateVersion.version_number <= number
            )
        )

    async def clear_default(self, template_id: str) -> None:
        """Unsets `template_id` wherever a workspace has it as its default."""
        await self._session.execute(
            update(Workspace).where(Workspace.default_template_id == template_id).values(default_template_id=None)
        )
