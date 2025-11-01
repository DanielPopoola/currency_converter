import asyncio
import logging
from datetime import datetime
from decimal import Decimal

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from domain.exceptions.currency import ProviderError
from domain.models.currency import AggregatedRate, ExchangeRate
from infrastructure.providers.base import ExchangeRateProvider

logger = logging.getLogger(__name__)


class RateService:
    def __init__(
        self,
        primary_provider: ExchangeRateProvider,
        secondary_providers: list[ExchangeRateProvider],
    ):
        self.primary_provider = primary_provider
        self.secondary_providers = secondary_providers

    async def get_rate(self, from_currency: str, to_currency: str) -> ExchangeRate:

        aggregated = await self._aggregate_rates(from_currency, to_currency)

        rate = ExchangeRate(
            from_currency=aggregated.from_currency,
            to_currency=aggregated.to_currency,
            rate=aggregated.rate,
            timestamp=aggregated.timestamp,
            source="averaged" if len(aggregated.sources) > 1 else aggregated.sources[0],
        )
        return rate

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    async def _fetch_from_provider(
        self, provider: ExchangeRateProvider, from_currency: str, to_currency: str
    ) -> Decimal | None:
        try:
            return await provider.fetch_rate(from_currency, to_currency)
        except Exception as e:
            logger.error(f"Provider {provider.name} failed: {e}")
            return None

    async def _aggregate_rates(
        self, from_currency: str, to_currency: str
    ) -> AggregatedRate:
        tasks = []
        providers = [self.primary_provider] + self.secondary_providers
        for provider in providers:
            tasks.append(
                self._fetch_from_provider(provider, from_currency, to_currency)
            )

        results = await asyncio.gather(*tasks)

        rates: dict[str, Decimal] = {}
        for provider, rate in zip(providers, results, strict=False):
            if rate is not None:
                rates[provider.name] = rate

        if not rates:
            raise ProviderError(f"All providers failed for {from_currency} → {to_currency}")

        avg_rate = sum(rates.values()) / len(rates)

        return AggregatedRate(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=avg_rate,
            timestamp=datetime.now(),
            sources=list(rates.keys()),
            individual_rates=rates,
        )