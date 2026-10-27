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
- Files in storage (pictures, kept originals, a job's upload, an export's file, each
  document's project thumbnail and its revision marker, an upload in parts not yet
  finished) can't be deleted inside the transaction (a rollback can't bring a file
  back), so their keys are gathered first and the files deleted once the rows are gone
  (B-040: the thumbnails and unfinished uploads were left behind before). Only the
  deleted workspaces' files: a shared workspace the user only leaves keeps all of its.

Everything in the database goes in one transaction: all of it, or nothing.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document as DocumentRow
from app.db.models import DocumentAsset, ProcessingJob, Subscription, User, Workspace, WorkspaceMember, WorkspaceRole
from app.jobs import uploads
from app.services.document_service import thumbnail_keys
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
    # Where an upload in parts of a deleted workspace may still sit (its keys are only known by listing).
    storage_prefixes: list[str] = field(default_factory=list)


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
    # Each document's project thumbnail and the revision it shows (DocumentService.thumbnail), drawn or not:
    # deleting a key that was never written is no error.
    for document_id in await session.scalars(select(DocumentRow.id).where(DocumentRow.workspace_id.in_(workspace_ids))):
        keys.extend(thumbnail_keys(document_id))
    return list(dict.fromkeys(keys))


async def delete_account(session: AsyncSession, user: User) -> DeletedAccount:
    """Deletes `user` and what goes with them, committed; AccountDeletionRefused, with
    nothing deleted, when the policy above refuses. The caller checks the password and
    deletes the files afterwards."""
    workspace_ids = await _workspaces_to_delete(session, user)
    if workspace_ids:
        renewing = await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.workspace_id.in_(workspace_ids),
                Subscription.stripe_subscription_id.is_not(None),  # paid through Stripe (no plan name in code)
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
        deleted.storage_prefixes = [f"{uploads.PREFIX}{workspace_id}/" for workspace_id in workspace_ids]
        await session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    return deleted


def _uploads_prefix_of_one_workspace(prefix: str) -> bool:
    """Exactly `uploads/<workspace id>/`: never the whole uploads folder, never a path deeper or beside it."""
    parts = prefix.split("/")
    return prefix.startswith(uploads.PREFIX) and len(parts) == 3 and bool(parts[1]) and parts[2] == ""


async def delete_files(storage: StorageProvider, keys: list[str], prefixes: list[str] | None = None) -> int:
    """Deletes what a deleted account left in storage, after the commit (a background
    task): `keys`, and whatever is under `prefixes` (a deleted workspace's unfinished
    uploads, `uploads/<workspace id>/` only). Each key once; one already gone counts as
    deleted. A file that can't be deleted is logged by its key -- opaque, nothing of the
    user's in it -- for someone to remove by hand, and the rest go on. A cleanup that
    couldn't do everything says so in one line (how many deleted, failed, folders not
    listed): a store that can't list leaves those uploads to their own sweep, which can't
    list them either -- they stay, bounded by uploads.MAX_OPEN_UPLOADS per workspace.
    Returns how many were deleted."""
    listed: list[str] = []
    unlisted = 0
    for prefix in prefixes or []:
        if not _uploads_prefix_of_one_workspace(prefix):
            logger.warning("Not one deleted workspace's uploads folder, left alone: %s", prefix)
            unlisted += 1
            continue
        try:
            # Only what is under the prefix, whatever the store answers.
            listed += [key for key, _ in await storage.list(prefix) if key.startswith(prefix)]
        except NotImplementedError:
            unlisted += 1
        except Exception:  # noqa: BLE001 -- counted below; left to the uploads' own sweep (jobs/uploads.py)
            logger.warning("A deleted account's unfinished uploads couldn't be listed: %s", prefix, exc_info=True)
            unlisted += 1
    deleted = failed = 0
    for key in dict.fromkeys([*keys, *listed]):
        try:
            await storage.delete(key)
            deleted += 1
        except Exception:  # noqa: BLE001 -- after the answer there is no one to tell but the log
            failed += 1
            logger.warning("A deleted account's file couldn't be deleted from storage: %s", key, exc_info=True)
    if failed or unlisted:
        logger.warning(
            "A deleted account's storage cleanup is incomplete: %d deleted, %d failed, %d upload folders not listed", deleted, failed, unlisted
        )
    return deleted
