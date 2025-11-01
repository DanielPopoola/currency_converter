import contextlib
from decimal import Decimal

import httpx

from domain.exceptions.currency import ProviderError


class CurrencyAPIProvider:
    BASE_URL = "https://api.currencyapi.com/v3"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None, timeout: int = 10):
        self.api_key = api_key
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"apikey": api_key},
        )

    @property
    def name(self) -> str:
        return "currencyapi.com"

    async def _request(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                message = data["error"].get("message", "Unknown error")
                raise ProviderError(f"CurrencyAPI error: {message}")

            return data

        except httpx.HTTPStatusError as e:
            msg = None
            with contextlib.suppress(Exception):
                msg = e.response.json().get("message")
            raise ProviderError(
                f"CurrencyAPI HTTP error {e.response.status_code}: {msg or e.response.text[:200]}"
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(f"CurrencyAPI request failed: {e.__class__.__name__}") from e
        except Exception as e:
            raise ProviderError(f"CurrencyAPI response parsing error: {str(e)}") from e

    async def fetch_rate(self, from_currency: str, to_currency: str) -> Decimal:
        data = await self._request(
            "latest",
            {"base_currency": from_currency, "currencies": to_currency},
        )

        try:
            rate_value = data["data"][to_currency]["value"]
            return Decimal(str(rate_value))
        except KeyError as e:
            raise ProviderError(f"Rate for {to_currency} not found in CurrencyAPI response") from e

    async def fetch_supported_currencies(self) -> list[dict]:
        data = await self._request("currencies")
        return [
            {
                "code": info.get("code", code),
                "name": info.get("name", "Unknown"),
            }
            for code, info in data.get("data", {}).items()
        ]

    async def close(self) -> None:
        await self._client.aclose()