from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from domain.models.currency import ExchangeRate, SupportedCurrency
from infrastructure.cache.redis_cache import RedisCacheService
from infrastructure.persistence.models.currency import (
	RateHistoryDB,
	SupportedCurrencyDB,
)


class CurrencyRepository:
	def __init__(self, db_session: AsyncSession, cache_service: RedisCacheService):
		self.db_session = db_session
		self.cache = cache_service

	async def get_supported_currencies(self) -> list[SupportedCurrency]:
		cached_codes = await self.cache.get_supported_currencies()
		if cached_codes:
			return [SupportedCurrency(code=code, name=None) for code in cached_codes]

		result = await self.db_session.execute(select(SupportedCurrencyDB))
		db_currencies = result.scalars().all()
		domain_currencies = [SupportedCurrency(code=c.code, name=c.name) for c in db_currencies]

		if domain_currencies:
			await self.cache.set_supported_currencies([c.code for c in domain_currencies])

		return domain_currencies

	async def save_supported_currencies(self, currencies: list[SupportedCurrency]) -> None:
		existing_codes = (
			(await self.db_session.execute(select(SupportedCurrencyDB.code))).scalars().all()
		)
		new_currencies = [c for c in currencies if c.code not in existing_codes]

		if new_currencies:
			self.db_session.add_all(
				[SupportedCurrencyDB(code=c.code, name=c.name) for c in new_currencies]
			)

	async def save_rate(self, rate: ExchangeRate) -> None:
		await self.cache.set_rate(rate)

		self.db_session.add(
			RateHistoryDB(
				from_currency=rate.from_currency,
				to_currency=rate.to_currency,
				rate=rate.rate,
				timestamp=rate.timestamp,
				source=rate.source,
			)
		)

	async def get_rate_history(
		self, from_currency: str, to_currency: str, since: datetime, limit: int = 100
	) -> list[ExchangeRate]:
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
		result = await self.db_session.execute(stmt)
		db_rates = result.scalars().all()
		return [
			ExchangeRate(
				from_currency=r.from_currency,
				to_currency=r.to_currency,
				rate=r.rate,
				timestamp=r.timestamp,
				source=r.source or 'unknown',
			)
			for r in db_rates
		]
