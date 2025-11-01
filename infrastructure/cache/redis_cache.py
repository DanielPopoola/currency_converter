import json
from datetime import datetime, timedelta
from decimal import Decimal

from redis import asyncio as redis

from domain.models.currency import ExchangeRate


class RedisCacheService:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.rate_ttl = timedelta(minutes=5)
        self.currency_ttl = timedelta(hours=24)

    def _make_rate_key(self, from_currency: str, to_currency: str) -> str:
        return f"rate:{from_currency}:{to_currency}"

    async def get_rate(self, from_currency: str, to_currency: str) -> ExchangeRate | None:
        key = self._make_rate_key(from_currency, to_currency)
        data = await self.redis.get(key)

        if not data:
            return None

        rate_dict = json.loads(data)
        return ExchangeRate(
            from_currency=rate_dict["from_currency"],
            to_currency=rate_dict["to_currency"],
            rate=Decimal(rate_dict["rate"]),
            timestamp=datetime.fromisoformat(rate_dict["timestamp"]),
            source=rate_dict["source"],
        )

    async def set_rate(self, rate: ExchangeRate) -> None:
        key = self._make_rate_key(rate.from_currency, rate.to_currency)

        rate_dict = {
            "from_currency": rate.from_currency,
            "to_currency": rate.to_currency,
            "rate": str(rate.rate),
            "timestamp": rate.timestamp.isoformat(),
            "source": rate.source,
        }

        await self.redis.setex(key, self.rate_ttl, json.dumps(rate_dict))

    async def get_supported_currencies(self) -> list[str] | None:
        data = await self.redis.get("currencies:supported")
        if not data:
            return None
        return json.loads(data)

    async def set_supported_currencies(self, currencies: list[str]) -> None:
        await self.redis.setex(
            "currencies:supported", self.currency_ttl, json.dumps(currencies)
        )
