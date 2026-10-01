"""Deleting an account and what goes with it (ACCT-005, brief §73).

The policy:
- The user's sessions, account tokens and memberships go with the user (the
  database's ON DELETE CASCADE).
- Each workspace the user is the only member of goes, and with it everything in it:
  documents and their versions, pictures and kept originals (asset rows), templates
  and their versions, formatting profiles, jobs, usage records and the subscription.
- In a workspace others are members of too, only the user's membership goes, and what
  they made there stays, no longer theirs (`created_by` is set to null). A workspace
  whose only owner is this user, with others in it, can't lose its owner that way:
  the deletion is refused until someone else owns it.
- A paid subscription still renewing is refused: it is cancelled first (Plan and
  billing), so no one pays for an account that is gone. One already set to end at
  its period's end may go.
- Files in storage (pictures, kept originals, a job's upload, an export's file) can't
  be deleted inside the transaction (a rollback can't bring a file back), so their
  keys are gathered first and the files deleted once the rows are gone.

Everything in the database goes in one transaction: all of it, or nothing.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document as DocumentRow
from app.db.models import DocumentAsset, ProcessingJob, Subscription, User, Workspace, WorkspaceMember, WorkspaceRole
from app.services.entitlements_service import ENTITLED_STATUSES
from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)


class AccountDeletionRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class DeletedAccount:
    email: str
    workspaces: int = 0
    documents: int = 0
    # What is left in storage to delete, once the rows are committed away.
    storage_keys: list[str] = field(default_factory=list)


async def _workspaces_to_delete(session: AsyncSession, user: User) -> list[str]:
    memberships = (await session.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))).all()
    alone: list[str] = []
    for membership in memberships:
        others = await session.scalar(
            select(func.count(WorkspaceMember.id)).where(WorkspaceMember.workspace_id == membership.workspace_id, WorkspaceMember.user_id != user.id)
        )
        if not others:
            alone.append(membership.workspace_id)
            continue
        other_owners = await session.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == membership.workspace_id,
                WorkspaceMember.user_id != user.id,
                WorkspaceMember.role == WorkspaceRole.OWNER.value,
            )
        )
        if membership.role == WorkspaceRole.OWNER.value and not other_owners:
            raise AccountDeletionRefused(
                "workspace_has_members", "You own a workspace others are members of. Make one of them its owner first, then delete your account."
            )
    return alone


async def _files_of(session: AsyncSession, workspace_ids: list[str]) -> list[str]:
    keys = list(await session.scalars(select(DocumentAsset.storage_key).where(DocumentAsset.workspace_id.in_(workspace_ids))))
    for input_key, result in (await session.execute(select(ProcessingJob.input_key, ProcessingJob.result).where(ProcessingJob.workspace_id.in_(workspace_ids)))).all():
        if input_key:
            keys.append(input_key)
        if isinstance(result, dict) and isinstance(result.get("key"), str):
            keys.append(result["key"])
    return keys


async def delete_account(session: AsyncSession, user: User) -> DeletedAccount:
    """Deletes `user` and what goes with them, committed; AccountDeletionRefused, with
    nothing deleted, when the policy above refuses. The caller checks the password and
    deletes the files afterwards."""
    workspace_ids = await _workspaces_to_delete(session, user)
    if workspace_ids:
        renewing = await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.workspace_id.in_(workspace_ids),
                Subscription.plan != "free",
                Subscription.status.in_(ENTITLED_STATUSES),
                Subscription.cancel_at_period_end.is_(False),
            )
        )
        if renewing:
            raise AccountDeletionRefused(
                "subscription_active", "Your plan still renews. Cancel it in Plan and billing first, then delete your account."
            )
    deleted = DeletedAccount(email=user.email, workspaces=len(workspace_ids))
    if workspace_ids:
        deleted.documents = int(await session.scalar(select(func.count(DocumentRow.id)).where(DocumentRow.workspace_id.in_(workspace_ids))) or 0)
        deleted.storage_keys = await _files_of(session, workspace_ids)
        await session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    return deleted


async def delete_files(storage: StorageProvider, keys: list[str]) -> int:
    """Deletes what a deleted account left in storage, after the commit (a background
    task). A file that can't be deleted is logged by its key -- opaque, nothing of the
    user's in it -- for someone to remove by hand, and the rest go on. Returns how
    many were deleted."""
    deleted = 0
    for key in keys:
        try:
            await storage.delete(key)
            deleted += 1
        except Exception:  # noqa: BLE001 -- after the answer there is no one to tell but the log
            logger.warning("A deleted account's file couldn't be deleted from storage: %s", key, exc_info=True)
    return deleted
