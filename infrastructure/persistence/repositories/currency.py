from datetime import datetime

from sqlalchemy.future import select

from domain.models.currency import ExchangeRate, SupportedCurrency
from infrastructure.cache.redis_cache import RedisCacheService
from infrastructure.persistence.models.currency import (
    RateHistoryDB,
    SupportedCurrencyDB,
)


class CurrencyRepository:
    def __init__(self, db_session_factory, cache_service: RedisCacheService):
        self.db_session_factory = db_session_factory
        self.cache = cache_service

    async def get_supported_currencies(self) -> list[SupportedCurrency]:

        cached_codes = await self.cache.get_supported_currencies()
        if cached_codes:
            return [SupportedCurrency(code=code, name=None) for code in cached_codes]

        async with self.db_session_factory() as session:
            result = await session.execute(select(SupportedCurrencyDB))
            db_currencies = result.scalars().all()
            domain_currencies = [
                SupportedCurrency(code=c.code, name=c.name) for c in db_currencies
            ]

        if domain_currencies:
            await self.cache.set_supported_currencies(
                [c.code for c in domain_currencies]
            )

        return domain_currencies

    async def save_supported_currencies(
        self, currencies: list[SupportedCurrency]
    ) -> None:
        async with self.db_session_factory() as session:
            existing_codes = (
                await session.execute(select(SupportedCurrencyDB.code))
                ).scalars().all()
            new_currencies = [c for c in currencies if c.code not in existing_codes]

            if new_currencies:
                session.add_all(
                    [SupportedCurrencyDB(code=c.code, name=c.name) for c in new_currencies]
                )
                await session.commit()

    async def save_rate(self, rate: ExchangeRate) -> None:
        await self.cache.set_rate(rate)

        async with self.db_session_factory() as session:
            session.add(
                RateHistoryDB(
                    from_currency=rate.from_currency,
                    to_currency=rate.to_currency,
                    rate=rate.rate,
                    timestamp=rate.timestamp,
                    source=rate.source,
                )
            )
            await session.commit()

    async def get_rate_history(
        self, from_currency: str, to_currency: str, since: datetime, limit: int = 100
    ) -> list[ExchangeRate]:
        async with self.db_session_factory() as session:
            stmt = (
                select(RateHistoryDB)
                .filter(
                    RateHistoryDB.from_currency == from_currency,
                    RateHistoryDB.to_currency == to_currency,
                    RateHistoryDB.timestamp >= since,
                )
                .order_by(RateHistoryDB.timestamp.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            db_rates = result.scalars().all()
            return [
                ExchangeRate(
                    from_currency=r.from_currency,
                    to_currency=r.to_currency,
                    rate=r.rate,
                    timestamp=r.timestamp,
                    source=r.source,
                )
                for r in db_rates
            ]