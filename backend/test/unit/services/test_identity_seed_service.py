from yuxi.services.identity_seed_service import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_USERS,
    SEED_FLAG_ENV,
    is_default_account_seed_enabled,
)


def test_default_account_seed_disabled_by_default(monkeypatch):
    monkeypatch.delenv(SEED_FLAG_ENV, raising=False)

    assert is_default_account_seed_enabled() is False


def test_default_account_seed_enabled_values(monkeypatch):
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv(SEED_FLAG_ENV, value)

        assert is_default_account_seed_enabled() is True


def test_default_identity_seed_definitions_are_consistent():
    department_names = {department.name for department in DEFAULT_DEPARTMENTS}
    user_ids = [user.user_id for user in DEFAULT_USERS]
    usernames = [user.username for user in DEFAULT_USERS]

    assert len(user_ids) == len(set(user_ids))
    assert len(usernames) == len(set(usernames))
    assert {user.department_name for user in DEFAULT_USERS}.issubset(department_names)
    assert {"superadmin", "admin", "user"} >= {user.role for user in DEFAULT_USERS}
