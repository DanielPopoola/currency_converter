import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ExchangeRateResponse:
    """Standardized response from any API provider"""
    base_currency: str
    target_currency: str
    rate: float
    timestamp: datetime
    provider_name: str
    raw_response: dict[str, Any]  # Original API response for debugging
    is_successful: bool = True
    error_message: str | None = None

ParsedData = ExchangeRateResponse | List[ExchangeRateResponse] | list[str]

@dataclass
class APICallResult:
    """Tracks the API call performance and outcome"""
    provider_name: str
    endpoint: str
    http_status_code: int | None
    response_time_ms: int
    was_successful: bool
    error_message: str | None = None
    data: ParsedData | None = None
    raw_response: dict[str, Any] | None = None


class APIProvider(ABC):
    """Abstract base class for all currency API providers"""

    def __init__(self, api_key: str, base_url: str, name: str, timeout: int = 3):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.name = name
        self.timeout = timeout

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"accept": "application/json"},
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

    @abstractmethod
    async def get_exchange_rate(self, base: str, target: str) -> APICallResult:
        """Get single currency pair exchange rate"""
        pass
    
    @abstractmethod
    async def get_all_rates(self, base: str) -> APICallResult:
        """Get all rates for a base currency"""
        pass
    
    @abstractmethod
    async def get_supported_currencies(self) -> APICallResult:
        """Get list of all supported currencies"""
        pass
    
    @abstractmethod
    def _parse_rate_response(self, response_data: dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        """Parse API-specific response format into standardized format"""
        pass
    
    @abstractmethod
    def _build_request_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build API-specific request URL with authentication"""
        pass

    async def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> APICallResult:
        """Common HTTP request handling with timing and error management"""
        start_time = datetime.now()
        url = self._build_request_url(endpoint, params or {})
        logger.info(f"Fetching data from URL: {url}")

        try:
            logger.debug(f"Calling {self.name} API: {endpoint}")

            response = await self.client.get(url)
            response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if response.status_code == 200:
                return APICallResult(
                    provider_name=self.name,
                    endpoint=endpoint,
                    http_status_code=response.status_code,
                    response_time_ms=response_time_ms,
                    was_successful=True,
                    raw_response=response.json()
                )
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.warning(f"{self.name} API error: {error_msg}")
                
                return APICallResult(
                    provider_name=self.name,
                    endpoint=endpoint,
                    http_status_code=response.status_code,
                    response_time_ms=response_time_ms,
                    was_successful=False,
                    error_message=error_msg
                )
                
        except httpx.TimeoutException:
            response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            error_msg = f"Timeout after {self.timeout}s"
            logger.warning(f"{self.name} API timeout: {error_msg}")

            return APICallResult(
                provider_name=self.name,
                endpoint=endpoint,
                http_status_code=None,
                response_time_ms=response_time_ms,
                was_successful=False,
                error_message=error_msg
            )
            
        except Exception as e:
            response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            error_msg = f"Network error: {str(e)}"
            logger.error(f"{self.name} API error: {error_msg}")
            
            return APICallResult(
                provider_name=self.name,
                endpoint=endpoint,
                http_status_code=None,
                response_time_ms=response_time_ms,
                was_successful=False,
                error_message=error_msg
            )

    async def close(self):
        """Clean up HTTP client"""
        await self.client.aclose()