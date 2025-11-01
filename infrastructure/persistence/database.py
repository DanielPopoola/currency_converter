from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from infrastructure.persistence.models.currency import Base

settings = get_settings()


class Database:
    def __init__(self, db_url: str = settings.DATABASE_URL):
        self.engine = create_async_engine(db_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine, autoflush=False, expire_on_commit=False
        )

    async def create_db_and_tables(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


database = Database()