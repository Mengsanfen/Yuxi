"""Seed the default tenant with enterprise customer-service demo data."""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

async def main() -> None:
    from yuxi.services.enterprise_seed_service import ensure_enterprise_demo_seed
    from yuxi.storage.postgres.manager import pg_manager

    pg_manager.initialize()
    try:
        await pg_manager.create_business_tables()
        result = await ensure_enterprise_demo_seed()
        print(result)
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
