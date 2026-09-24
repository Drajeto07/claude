from argon2 import PasswordHasher
from sqlalchemy import select

from app.db.models import User
from app.services import auth_service
from app.services.auth_service import AuthService


async def test_login_upgrades_a_hash_made_with_outdated_parameters(db_session):
    old_hasher = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1, hash_len=4, salt_len=8)
    await AuthService(db_session).register("a@example.com", "long enough password", None)
    user = (await db_session.execute(select(User))).scalar_one()
    user.hashed_password = old_hasher.hash("long enough password")
    await db_session.commit()
    outdated = user.hashed_password

    assert await AuthService(db_session).authenticate("a@example.com", "long enough password") is not None

    await db_session.refresh(user)
    assert user.hashed_password != outdated
    assert not auth_service._hasher.check_needs_rehash(user.hashed_password)


async def test_default_workspace_is_the_personal_one_created_at_registration(db_session):
    service = AuthService(db_session)
    user = await service.register("b@example.com", "long enough password", None)

    workspace_id = await service.default_workspace_id(user.id)

    assert workspace_id
    assert (await service.default_workspace_id(user.id)) == workspace_id
