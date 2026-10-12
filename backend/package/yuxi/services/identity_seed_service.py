"""Seed demo departments and users for local development."""

import os
from dataclasses import dataclass

from sqlalchemy import or_, select

from server.utils.auth_utils import AuthUtils
from yuxi.storage.postgres.manager import pg_manager
from yuxi.storage.postgres.models_business import Department, User
from yuxi.utils import logger

SEED_FLAG_ENV = "YUXI_SEED_DEFAULT_ACCOUNTS"
DEFAULT_SEED_PASSWORD = os.getenv("YUXI_DEFAULT_ACCOUNT_PASSWORD", "NexaMind@2026")


@dataclass(frozen=True)
class SeedDepartment:
    name: str
    description: str


@dataclass(frozen=True)
class SeedUser:
    username: str
    user_id: str
    role: str
    department_name: str


DEFAULT_DEPARTMENTS = (
    SeedDepartment("默认部门", "平台初始化默认部门"),
    SeedDepartment("研发中心", "负责核心平台、智能体编排与工程交付"),
    SeedDepartment("产品运营部", "负责产品规划、内容运营与用户增长"),
    SeedDepartment("数据智能部", "负责知识库治理、评测分析与数据应用"),
    SeedDepartment("客户成功部", "负责客户支持、方案落地与交付跟进"),
)

DEFAULT_USERS = (
    SeedUser("平台管理员", "nexamind_admin", "superadmin", "默认部门"),
    SeedUser("研发管理员", "rd_admin", "admin", "研发中心"),
    SeedUser("产品管理员", "product_admin", "admin", "产品运营部"),
    SeedUser("数据管理员", "data_admin", "admin", "数据智能部"),
    SeedUser("研发成员", "rd_user", "user", "研发中心"),
    SeedUser("客服成员", "cs_user", "user", "客户成功部"),
)


def is_default_account_seed_enabled() -> bool:
    return os.getenv(SEED_FLAG_ENV, "false").lower() in {"1", "true", "yes", "on"}


async def ensure_default_identity_seed() -> None:
    """Create default demo departments and users when explicitly enabled."""
    if not is_default_account_seed_enabled():
        return

    created_departments = 0
    created_users = 0
    password_hash = AuthUtils.hash_password(DEFAULT_SEED_PASSWORD)

    async with pg_manager.get_async_session_context() as session:
        department_map: dict[str, Department] = {}
        for item in DEFAULT_DEPARTMENTS:
            result = await session.execute(select(Department).where(Department.name == item.name))
            department = result.scalar_one_or_none()
            if department is None:
                department = Department(name=item.name, description=item.description)
                session.add(department)
                await session.flush()
                created_departments += 1
            department_map[item.name] = department

        for item in DEFAULT_USERS:
            result = await session.execute(
                select(User).where(or_(User.user_id == item.user_id, User.username == item.username))
            )
            if result.scalar_one_or_none() is not None:
                continue

            department = department_map[item.department_name]
            session.add(
                User(
                    username=item.username,
                    user_id=item.user_id,
                    phone_number=None,
                    avatar=None,
                    password_hash=password_hash,
                    role=item.role,
                    department_id=department.id,
                )
            )
            created_users += 1

    if created_departments or created_users:
        logger.info(
            "Default identity seed applied: "
            f"{created_departments} departments, {created_users} users."
        )
