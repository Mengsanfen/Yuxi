"""Create an isolated, indexed policy knowledge base for local enterprise demos."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

POLICY_FILE = BACKEND_ROOT / "eval" / "enterprise" / "fixtures" / "dreamos_refund_policy.md"
DOCUMENT_FILES = (
    POLICY_FILE,
    POLICY_FILE.with_name("dreamos_product_catalog.md"),
    POLICY_FILE.with_name("dreamos_after_sale_guide.md"),
)
KB_NAME = "DreamOS 企业售后演示知识库"
KB_DESCRIPTION = "本地演示用产品、退款与售后资料"


async def seed(*, bind_agent: bool = False) -> dict[str, str]:
    from yuxi import config, knowledge_base
    from yuxi.repositories.agent_config_repository import AgentConfigRepository
    from yuxi.storage.postgres.manager import pg_manager
    from yuxi.storage.postgres.models_business import Department, User
    from yuxi.storage.postgres.models_knowledge import KnowledgeBase, KnowledgeFile

    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as session:
            department = (
                await session.execute(select(Department).where(Department.name == "默认部门"))
            ).scalar_one()
            actor = (
                await session.execute(
                    select(User)
                    .where(User.department_id == department.id, User.role == "superadmin", User.is_deleted == 0)
                    .limit(1)
                )
            ).scalar_one()
            existing = (
                await session.execute(select(KnowledgeBase).where(KnowledgeBase.name == KB_NAME))
            ).scalar_one_or_none()
            document_records = []
            if existing is not None:
                records = await session.execute(
                    select(KnowledgeFile).where(
                        KnowledgeFile.db_id == existing.db_id,
                        KnowledgeFile.filename.in_([path.name for path in DOCUMENT_FILES]),
                    )
                )
                document_records = list(records.scalars().all())

        if existing is None:
            embed_info = config.embed_model_names["siliconflow/BAAI/bge-m3"].model_dump()
            created = await knowledge_base.create_database(
                KB_NAME,
                KB_DESCRIPTION,
                kb_type="milvus",
                embed_info=embed_info,
                share_config={"is_shared": False, "accessible_departments": [department.id]},
            )
            db_id = created["db_id"]
        else:
            if (
                existing.kb_type != "milvus"
                or existing.share_config != {"is_shared": False, "accessible_departments": [department.id]}
            ):
                raise RuntimeError("Same-name KB is not the isolated local demo KB")
            db_id = existing.db_id
        if existing is not None:
            await knowledge_base.get_databases()
        file_ids = {}
        for document_path in DOCUMENT_FILES:
            document_hash = hashlib.sha256(document_path.read_bytes()).hexdigest()
            matching = [record for record in document_records if record.filename == document_path.name]
            current = next(
                (
                    record for record in matching
                    if record.content_hash == document_hash and record.status in {"indexed", "done"}
                ),
                None,
            ) or next((record for record in matching if record.content_hash == document_hash), None)
            stale = [record for record in matching if record.content_hash != document_hash]
            if current is not None and current.status in {"indexed", "done"}:
                file_ids[document_path.name] = current.file_id
            else:
                if current is None:
                    document = await knowledge_base.add_file_record(
                        db_id,
                        str(document_path),
                        params={"content_type": "file"},
                        operator_id=actor.user_id,
                    )
                else:
                    info = await knowledge_base.get_database_info(db_id)
                    document = next(
                        (item for item in (info.get("files") or {}).values() if item.get("file_id") == current.file_id),
                        None,
                    )
                    if document is None:
                        raise RuntimeError(f"Document metadata is missing: {current.file_id}")
                file_id = document["file_id"]
                if document.get("status") not in {"parsed", "indexed", "done"}:
                    document = await knowledge_base.parse_file(db_id, file_id, operator_id=actor.user_id)
                if document.get("status") not in {"indexed", "done"}:
                    document = await knowledge_base.index_file(db_id, file_id, operator_id=actor.user_id)
                if document.get("status") not in {"indexed", "done"}:
                    raise RuntimeError(
                        f"Document indexing did not complete: {document_path.name}: {document.get('status')}"
                    )
                file_ids[document_path.name] = file_id
            for record in stale:
                await knowledge_base.delete_file(db_id, record.file_id)

        if bind_agent:
            async with pg_manager.get_async_session_context() as session:
                repo = AgentConfigRepository(session)
                agent_config = await repo.get_or_create_default(
                    department_id=department.id,
                    agent_id="EnterpriseServiceAgent",
                    created_by=actor.user_id,
                )
                settings = dict(agent_config.config_json or {})
                context_settings = dict(settings.get("context") or {})
                context_settings["knowledges"] = list(dict.fromkeys([
                    *(context_settings.get("knowledges") or []),
                    *(settings.pop("knowledges", None) or []),
                    KB_NAME,
                ]))
                settings["context"] = context_settings
                await repo.update(
                    agent_config,
                    config_json=settings,
                    updated_by=actor.user_id,
                )
        return {"knowledge_base": KB_NAME, "db_id": db_id, "file_id": file_ids[POLICY_FILE.name], "file_ids": file_ids}
    finally:
        await pg_manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the local enterprise demo policy KB")
    parser.add_argument("--bind-agent", action="store_true", help="Enable the KB on the default enterprise Agent")
    args = parser.parse_args()
    print(asyncio.run(seed(bind_agent=args.bind_agent)))


if __name__ == "__main__":
    main()
