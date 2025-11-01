from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.persistence.models.currency import Base


class Database:
    def __init__(self, db_url: str):
        self.engine = create_async_engine(db_url)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            autoflush=True,
            expire_on_commit=False   
        )

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self):
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()