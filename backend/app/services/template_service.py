"""The templates a user can see and use: the built-ins (formatting/templates.py)
plus their workspaces' own, stored in the database (корекции.docx §18). One
instance per request, acting for one signed-in user; every template API call
and every "format with template X" goes through here."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.config import get_settings
from app.db.models import Template as TemplateRow
from app.db.models import TemplateVersion, TemplateVisibility, Workspace, WorkspaceMember, WorkspaceRole
from app.formatting.engine import DEFAULT_RULES, extract_settings, resolve_styles
from app.formatting.priorities import Priority
from app.formatting.style_system import StyleSystem, compile_rules, style_system_from_rules
from app.formatting.templates import BUILTIN_TEMPLATES, BuiltinTemplate, UnknownTemplateError
from app.models.document import DocumentSettings, FormattingRule
from app.repositories.document_repository import DocumentRepository
from app.repositories.template_repository import TemplateRepository
from app.services.auth_service import AuthService


class TemplateNotFoundError(Exception):
    """No such template, or not one this user can see (the API answers 404 for both)."""


class TemplateReadOnlyError(Exception):
    """The user can see the template but not change it (403)."""


class TemplateVersionConflictError(Exception):
    """The template was saved elsewhere since the caller loaded it (412)."""

    def __init__(self, current_version: int | None) -> None:
        self.current_version = current_version
        super().__init__("The template was changed elsewhere since it was loaded.")


class TemplateNotSharedError(Exception):
    """A private template can't be the workspace's default (409)."""


class SourceDocumentNotFoundError(Exception):
    """The document to save a template from doesn't exist or isn't the user's (404)."""


_BUILTIN_IS_READ_ONLY = "Built-in templates can't be changed. Duplicate it to make your own copy."
_COPY_SUFFIX = " (copy)"


@dataclass(frozen=True)
class TemplateView:
    id: str
    name: str
    category: str
    description: str
    style_system: StyleSystem
    builtin: bool
    editable: bool
    is_default: bool
    visibility: str | None = None  # None for built-ins: everyone has those
    version: int | None = None
    source_document_id: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class TemplateVersionView:
    number: int
    name: str
    created_at: datetime
    author: str | None
    current: bool


def preview_styles(style_system: StyleSystem) -> tuple[dict[str, dict[str, str]], DocumentSettings]:
    """What a document formatted with `style_system` (and nothing else) resolves
    to, computed by the real engine so previews can't drift from the editor."""
    rules = [*DEFAULT_RULES, *compile_rules(style_system, priority=Priority.CUSTOM_TEMPLATE, source="custom_template")]
    return resolve_styles(rules), extract_settings(rules)


def _compiled(style_system: StyleSystem) -> list[dict]:
    return [
        rule.model_dump(mode="json")
        for rule in compile_rules(style_system, priority=Priority.CUSTOM_TEMPLATE, source="custom_template")
    ]


def _stored(style_system: StyleSystem) -> dict:
    # Unset fields left out: they mean "not set" either way, and it keeps rows small.
    return style_system.model_dump(mode="json", exclude_none=True)


def _copy_name(name: str) -> str:
    return name[: 255 - len(_COPY_SUFFIX)] + _COPY_SUFFIX


class TemplateService:
    def __init__(self, session: AsyncSession, *, user_id: str) -> None:
        self._session = session
        self._repo = TemplateRepository(session)
        self._user_id = user_id
        self._workspace_id: str | None = None

    # -- reading -----------------------------------------------------------

    async def list_visible(self) -> list[TemplateView]:
        """Built-ins first (in their file order), then the workspace's own by name."""
        default_id = await self.default_template_id()
        builtins = [self._builtin_view(template, default_id) for template in BUILTIN_TEMPLATES.values()]
        own = [self._row_view(row, role, default_id) for row, role in await self._repo.list_visible(self._user_id)]
        return [*builtins, *own]

    async def get(self, template_id: str) -> TemplateView:
        default_id = await self.default_template_id()
        builtin = BUILTIN_TEMPLATES.get(template_id)
        if builtin is not None:
            return self._builtin_view(builtin, default_id)
        row, role = await self._visible_row(template_id)
        return self._row_view(row, role, default_id)

    async def rules_for(self, template_id: str) -> list[FormattingRule]:
        """The rules formatting a document with this template applies.
        UnknownTemplateError if the user has no such template."""
        builtin = BUILTIN_TEMPLATES.get(template_id)
        if builtin is not None:
            return builtin.rules
        found = await self._repo.get_visible(template_id, self._user_id)
        if found is None:
            raise UnknownTemplateError(template_id)
        return [FormattingRule.model_validate(rule) for rule in found[0].rules]

    async def versions(self, template_id: str) -> list[TemplateVersionView]:
        """Newest first. Built-ins have no history of their own."""
        if template_id in BUILTIN_TEMPLATES:
            return []
        row, _ = await self._visible_row(template_id)
        return [
            TemplateVersionView(
                number=version.version_number,
                name=version.data.get("name", ""),
                created_at=version.created_at,
                author=author,
                current=version.version_number == row.version,
            )
            for version, author in await self._repo.versions(row.id)
        ]

    async def default_template_id(self) -> str | None:
        """The workspace's default template, or None when it has none or the one
        it had is no longer usable (deleted, or made private since)."""
        workspace = await self._session.get(Workspace, await self._current_workspace_id())
        default_id = workspace.default_template_id if workspace else None
        if default_id is None or default_id in BUILTIN_TEMPLATES:
            return default_id
        found = await self._repo.get_visible(default_id, self._user_id)
        if found is None or found[0].visibility != TemplateVisibility.WORKSPACE.value:
            return None
        return default_id

    # -- writing -----------------------------------------------------------

    async def create(
        self,
        *,
        name: str,
        category: str,
        description: str,
        style_system: StyleSystem,
        visibility: TemplateVisibility = TemplateVisibility.WORKSPACE,
        source_document_id: str | None = None,
        workspace_id: str | None = None,
    ) -> TemplateView:
        row = TemplateRow(
            workspace_id=workspace_id or await self._current_workspace_id(),
            created_by=self._user_id,
            source_document_id=source_document_id,
            name=name.strip(),
            category=category.strip(),
            description=description.strip(),
            visibility=visibility.value,
            style_system=_stored(style_system),
            rules=_compiled(style_system),
        )
        self._repo.add(row)
        await self._save(row)
        return self._row_view(row, role=None, default_id=None)

    async def create_from_document(
        self,
        document_id: str,
        *,
        name: str,
        category: str,
        description: str,
        visibility: TemplateVisibility = TemplateVisibility.WORKSPACE,
    ) -> tuple[TemplateView, list[str]]:
        """Saves a document's current look (its type-level formatting, not the
        one-off overrides on single paragraphs) as a template in the document's
        own workspace. Also returns notes on anything that couldn't be carried over."""
        documents = DocumentRepository(self._session)
        row = await documents.get_row_for_user(document_id, self._user_id)
        if row is None:
            raise SourceDocumentNotFoundError(document_id)
        style_system, notes = style_system_from_rules(documents.to_model(row).formattingRules)
        view = await self.create(
            name=name,
            category=category,
            description=description,
            style_system=style_system,
            visibility=visibility,
            source_document_id=row.id,
            workspace_id=row.workspace_id,
        )
        return view, notes

    async def duplicate(self, template_id: str, *, name: str | None = None) -> TemplateView:
        """A new template of the user's own, starting as a copy of any template
        they can see -- built-ins included, which is how those get customized."""
        source = await self.get(template_id)
        return await self.create(
            name=name or _copy_name(source.name),
            category=source.category,
            description=source.description,
            style_system=source.style_system.model_copy(deep=True),
        )

    async def update(
        self,
        template_id: str,
        *,
        expected_version: int | None,
        name: str | None = None,
        category: str | None = None,
        description: str | None = None,
        style_system: StyleSystem | None = None,
        visibility: TemplateVisibility | None = None,
    ) -> TemplateView:
        """Changes what was given, as one new version. Nothing given that differs
        from what's saved means nothing is written and no version is added."""
        row, role = await self._editable_row(template_id)
        if expected_version is not None and row.version != expected_version:
            raise TemplateVersionConflictError(row.version)

        changes: dict[str, object] = {}
        for field, value in (("name", name), ("category", category), ("description", description)):
            if value is not None and value.strip() != getattr(row, field):
                changes[field] = value.strip()
        if style_system is not None and _stored(style_system) != row.style_system:
            changes["style_system"] = _stored(style_system)
            changes["rules"] = _compiled(style_system)
        if visibility is not None and visibility.value != row.visibility:
            if row.created_by != self._user_id:
                raise TemplateReadOnlyError("Only the person who made a template can change who sees it.")
            changes["visibility"] = visibility.value
        if not changes:
            return self._row_view(row, role, await self.default_template_id())

        for field, value in changes.items():
            setattr(row, field, value)
        if changes.get("visibility") == TemplateVisibility.PRIVATE.value:
            # The workspace default has to be one the whole workspace can use.
            await self._repo.clear_default(row.id)
        await self._save(row)
        return self._row_view(row, role, await self.default_template_id())

    async def restore_version(self, template_id: str, number: int, *, expected_version: int | None) -> TemplateView:
        """Makes an earlier version current again, as a new version on top, so the
        restore itself can be undone the same way. Who can see it is not part of
        a version and stays as it is."""
        row, _ = await self._editable_row(template_id)
        version = await self._repo.version(row.id, number)
        if version is None:
            raise TemplateNotFoundError(f"{template_id} has no version {number}")
        data = version.data
        return await self.update(
            template_id,
            expected_version=expected_version,
            name=data["name"],
            category=data["category"],
            description=data["description"],
            style_system=StyleSystem.model_validate(data["styleSystem"]),
        )

    async def delete(self, template_id: str) -> None:
        """Documents formatted with it keep their formatting: each holds its own
        copy of the rules. The workspace default is cleared if it was this one."""
        row, _ = await self._editable_row(template_id)
        await self._repo.clear_default(row.id)
        await self._repo.delete(row)
        try:
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise TemplateVersionConflictError(None) from exc

    async def set_default(self, template_id: str | None) -> None:
        """Sets (or with None clears) the template new documents in the user's
        workspace start with. Only the workspace owner may, and only to a
        template the whole workspace can see."""
        workspace_id = await self._current_workspace_id()
        role = await self._session.scalar(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == self._user_id
            )
        )
        if role != WorkspaceRole.OWNER.value:
            raise TemplateReadOnlyError("Only the workspace owner can change its default template.")
        if template_id is not None and template_id not in BUILTIN_TEMPLATES:
            found = await self._repo.get_visible(template_id, self._user_id)
            if found is None or found[0].workspace_id != workspace_id:
                raise TemplateNotFoundError(template_id)
            if found[0].visibility != TemplateVisibility.WORKSPACE.value:
                raise TemplateNotSharedError("A private template can't be the workspace default. Share it first.")
        workspace = await self._session.get(Workspace, workspace_id)
        workspace.default_template_id = template_id
        await self._session.commit()

    # -- helpers -----------------------------------------------------------

    async def _current_workspace_id(self) -> str:
        if self._workspace_id is None:
            self._workspace_id = await AuthService(self._session).default_workspace_id(self._user_id)
        return self._workspace_id

    async def _visible_row(self, template_id: str) -> tuple[TemplateRow, str]:
        found = await self._repo.get_visible(template_id, self._user_id)
        if found is None:
            raise TemplateNotFoundError(template_id)
        return found

    async def _editable_row(self, template_id: str) -> tuple[TemplateRow, str]:
        if template_id in BUILTIN_TEMPLATES:
            raise TemplateReadOnlyError(_BUILTIN_IS_READ_ONLY)
        row, role = await self._visible_row(template_id)
        if not self._may_edit(row, role):
            raise TemplateReadOnlyError("Only the person who made this template or the workspace owner can change it.")
        return row, role

    def _may_edit(self, row: TemplateRow, role: str | None) -> bool:
        return row.created_by == self._user_id or role == WorkspaceRole.OWNER.value

    async def _save(self, row: TemplateRow) -> None:
        """Flushes the row (which assigns or bumps its version), records that
        version in the history, trims the oldest, commits."""
        try:
            await self._session.flush()
            self._session.add(
                TemplateVersion(
                    template_id=row.id,
                    version_number=row.version,
                    data={
                        "name": row.name,
                        "category": row.category,
                        "description": row.description,
                        "visibility": row.visibility,
                        "styleSystem": row.style_system,
                        "rules": row.rules,
                    },
                    created_by=self._user_id,
                )
            )
            keep = get_settings().template_history_max_versions
            await self._repo.drop_versions_up_to(row.id, row.version - keep)
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise TemplateVersionConflictError(None) from exc

    def _builtin_view(self, template: BuiltinTemplate, default_id: str | None) -> TemplateView:
        return TemplateView(
            id=template.id,
            name=template.name,
            category=template.category,
            description=template.description,
            style_system=template.styleSystem,
            builtin=True,
            editable=False,
            is_default=template.id == default_id,
        )

    def _row_view(self, row: TemplateRow, role: str | None, default_id: str | None) -> TemplateView:
        return TemplateView(
            id=row.id,
            name=row.name,
            category=row.category,
            description=row.description,
            style_system=StyleSystem.model_validate(row.style_system),
            builtin=False,
            editable=self._may_edit(row, role),
            is_default=row.id == default_id,
            visibility=row.visibility,
            version=row.version,
            source_document_id=row.source_document_id,
            updated_at=row.updated_at,
        )
