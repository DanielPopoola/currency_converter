import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from application.services import ConversionService, CurrencyService, RateService
from config.settings import get_settings
from infrastructure.cache.redis_cache import RedisCacheService
from infrastructure.persistence.database import Database
from infrastructure.persistence.repositories.currency import CurrencyRepository
from infrastructure.providers import (
	CurrencyAPIProvider,
	ExchangeRateProvider,
	FixerIOProvider,
	OpenExchangeProvider,
)

logger = logging.getLogger(__name__)


class AppDependencies:
	"""Container for application-wide singleton dependencies."""

	db: Database | None = None
	redis_client: Redis | None = None
	redis_cache: RedisCacheService | None = None
	providers: dict[str, ExchangeRateProvider] | None = None


deps = AppDependencies()


def init_dependencies() -> None:
	"""Initialize all singleton dependencies. Called at app startup."""
	logger.info('Initializing dependencies...')
	settings = get_settings()

	deps.db = Database(settings.DATABASE_URL)
	deps.redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
	deps.redis_cache = RedisCacheService(deps.redis_client)

	deps.providers = {
		'fixerio': FixerIOProvider(settings.FIXERIO_API_KEY),
		'openexchange': OpenExchangeProvider(settings.OPENEXCHANGE_APP_ID),
		'currencyapi': CurrencyAPIProvider(settings.CURRENCYAPI_KEY),
	}
	logger.info('Dependencies initialized')


async def cleanup_dependencies() -> None:
	logger.info('Cleaning up dependencies...')

	if deps.redis_client:
		await deps.redis_client.close()
	if deps.db:
		await deps.db.close()
	if deps.providers:
		for provider in deps.providers.values():
			await provider.close()

	logger.info('Cleanup complete')


async def bootstrap() -> None:
	"""Bootstrap application data. Called after init_dependencies() at startup."""
	logger.info('Bootstrapping application...')

	if deps.db is None or deps.redis_cache is None or deps.providers is None:
		raise RuntimeError('Dependencies not initialized. Call init_dependencies() first.')

	async with deps.db.managed_session() as session:
		repo = CurrencyRepository(db_session=session, cache_service=deps.redis_cache)
		service = CurrencyService(repository=repo, providers=list(deps.providers.values()))
		await service.initialize_supported_currencies()

	logger.info('Bootstrap complete')


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
	if deps.db is None:
		raise RuntimeError('Database is not initialized')

	session = deps.db.session_factory()
	try:
		yield session
		await session.commit()
	except Exception:
		await session.rollback()
		raise
	finally:
		await session.close()


def get_redis_cache() -> RedisCacheService:
	if deps.redis_cache is None:
		raise RuntimeError('Redis cache not initialized')
	return deps.redis_cache


def get_providers() -> dict[str, ExchangeRateProvider]:
	if deps.providers is None:
		raise RuntimeError('Providers not initialized')
	return deps.providers


async def get_currency_repository(
	session: Annotated[AsyncSession, Depends(get_db_session)],
	cache: Annotated[RedisCacheService, Depends(get_redis_cache)],
) -> CurrencyRepository:
	return CurrencyRepository(db_session=session, cache_service=cache)


async def get_currency_service(
	repository: Annotated[CurrencyRepository, Depends(get_currency_repository)],
	providers: Annotated[dict[str, ExchangeRateProvider], Depends(get_providers)],
) -> CurrencyService:
	return CurrencyService(repository=repository, providers=list(providers.values()))


async def get_rate_service(
	currency_service: Annotated[CurrencyService, Depends(get_currency_service)],
	providers: Annotated[dict[str, ExchangeRateProvider], Depends(get_providers)],
) -> RateService:
	return RateService(
		currency_service=currency_service,
		primary_provider=providers['fixerio'],
		secondary_providers=[providers['openexchange'], providers['currencyapi']],
	)


async def get_conversion_service(
	rate_service: Annotated[RateService, Depends(get_rate_service)],
	currency_service: Annotated[CurrencyService, Depends(get_currency_service)],
) -> ConversionService:
	return ConversionService(rate_service=rate_service, currency_service=currency_service)
