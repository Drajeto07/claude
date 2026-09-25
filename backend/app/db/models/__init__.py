"""Importing this package registers every ORM model on `Base`'s shared
registry -- required before `Base.metadata.create_all()`/Alembic autogenerate
sees the full schema, since relationships are resolved by class name (string)
rather than direct import between model modules."""

from app.db.base import Base
from app.db.models.auth_session import Session
from app.db.models.billing import Subscription, UsageRecord
from app.db.models.document import Document, DocumentAsset, DocumentVersion
from app.db.models.jobs import JobStatus, JobType, ProcessingJob
from app.db.models.template import FormattingProfile, Template, TemplateVersion, TemplateVisibility
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember, WorkspaceRole

__all__ = [
    "Base",
    "Document",
    "DocumentAsset",
    "DocumentVersion",
    "FormattingProfile",
    "JobStatus",
    "JobType",
    "ProcessingJob",
    "Session",
    "Subscription",
    "Template",
    "TemplateVersion",
    "TemplateVisibility",
    "UsageRecord",
    "User",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceRole",
]
