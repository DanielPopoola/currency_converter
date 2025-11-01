from decimal import Decimal


import httpx


from domain.exceptions.currency import ProviderError


class OpenExchangeProvider:
    BASE_URL = "https://openexchangerates.org/api"

    def __init__(self, app_id: str, client: httpx.AsyncClient | None = None, timeout: int = 10):
        self.app_id = app_id
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def name(self) -> str:
        return "openexchange"

    async def _request(self, endpoint: str, params: dict) -> dict:
        params["app_id"] = self.app_id
        url = f"{self.BASE_URL}/{endpoint}"

        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                message = data.get("description", data.get("message", "Unknown error"))
                raise ProviderError(f"OpenExchange API error: {message}")

            return data

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"OpenExchange HTTP error {e.response.status_code}: {e.response.text[:200]}"
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(f"OpenExchange request failed: {e.__class__.__name__}") from e
        except Exception as e:
            raise ProviderError(f"OpenExchange response parsing error: {str(e)}") from e

    async def fetch_rate(self, from_currency: str, to_currency: str) -> Decimal:
        data = await self._request("latest.json", {"base": from_currency, "symbols": to_currency})
        try:
            return Decimal(str(data["rates"][to_currency]))
        except KeyError as e:
            raise ProviderError(f"Missing rate for {to_currency}") from e

    async def fetch_supported_currencies(self) -> list[dict]:
        data = await self._request("currencies.json", {})
        return [{"code": code, "name": name} for code, name in data.items()]

    async def close(self) -> None:
        await self._client.aclose()