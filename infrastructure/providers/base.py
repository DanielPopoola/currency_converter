import httpx
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from domain.models.currency import APICallResult


class BaseAPIProvider(ABC):
    """A base class for API providers, handling common HTTP logic."""

    def __init__(
        self, base_url: str, api_key: str, name: str, timeout: int = 5
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = name
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def get_exchange_rate(self, from_currency: str, to_currency: str) -> APICallResult:
        ...

    @abstractmethod
    async def get_supported_currencies(self) -> APICallResult:
        ...

    async def _make_request(
        self, endpoint: str, params: dict | None = None
    ) -> APICallResult:
        """Common HTTP request handling with timing and error management."""
        start_time = datetime.now()
        url = self._build_request_url(endpoint, params or {})
        try:
            response = await self.client.get(url)
            response.raise_for_status()  # Raises HTTPStatusError for 4xx/5xx

            response_time_ms = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )

            return APICallResult(
                provider_name=self.name,
                endpoint=endpoint,
                http_status_code=response.status_code,
                response_time_ms=response_time_ms,
                was_successful=True,
                raw_response=response.json(),
            )

        except httpx.HTTPStatusError as e:
            # Handle HTTP errors specifically
            error_message = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except httpx.RequestError as e:
            # Handle network errors (timeout, connection error, etc.)
            error_message = f"Request failed: {e.__class__.__name__}"
        except Exception as e:
            # Handle other unexpected errors (e.g., JSON parsing)
            error_message = f"An unexpected error occurred: {str(e)}"

        return APICallResult(
            provider_name=self.name,
            endpoint=endpoint,
            http_status_code=e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None,
            response_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
            was_successful=False,
            error_message=error_message,
        )

    @abstractmethod
    def _build_request_url(self, endpoint: str, params: dict) -> str:
        ...

    async def close(self):
        """Cleanly close the HTTP client."""
        await self.client.aclose()
