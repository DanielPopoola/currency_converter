import os
import logging
from currencyapicom import Client
from datetime import datetime, UTC
from typing import Any


from .base import APIProvider, ExchangeRateResponse, APICallResult


logger = logging.getLogger(__name__)


class CurrencyAPIProvider(APIProvider):
    """Secondary provider implementation"""
    
    def __init__(self, api_key: str):
        api_key = os.getenv("CURRENCYAPI_KEY", "your_api_key")
        base_url = os.getenv("CURRENCYAPI_URL", "https://api.currencyapi.com/v3")

        super().__init__(
            api_key=api_key,
            base_url=base_url,
            name="CurrencyAPI",
            timeout=3
        )
        self.sdk_client = Client(api_key)

    def _build_request_url(self, endpoint: str, params: dict[str, Any]) -> str:
        raise NotImplementedError("CurrencyAPI SDK handles URLs internally")

    def _parse_rate_response(self, response_data: dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        raise NotImplementedError("CurrencyAPI SDK already parses responses")
    
    async def get_exchange_rate(self, base: str, target: str) -> APICallResult:
        """Get single currency pair from CurrencyAPI"""
        start_time = datetime.now(UTC)

        try:
            response = self.sdk_client.latest(base_currency=base, currencies=[target])
            logger.info(f"Fetching latest rate for {base}/{target} using CurrencyAPI SDK")

            rate_info = response["data"][target]
            last_updated = response["meta"]["last_updated_at"]
            timestamp = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))

            rate_response = ExchangeRateResponse(
                base_currency=base,
                target_currency=target,
                rate=rate_info["value"],
                timestamp=timestamp,
                provider_name=self.name,
                raw_response=response
            )
            logger.info("Rate for successfull parsed.")

            return APICallResult(
                provider_name=self.name,
                endpoint="latest",
                http_status_code=200,
                response_time_ms=int((datetime.now(tz=UTC) - start_time).total_seconds() * 1000),
                was_successful=True,
                data=rate_response,
                raw_response=response
            )
        
        except Exception as e:
            logger.error(f"Error while fetching data using CurrencyAPI SDK")
            return APICallResult(
                provider_name=self.name,
                endpoint="latest",
                http_status_code=None,
                response_time_ms=int((datetime.now(tz=UTC) - start_time).total_seconds() * 1000),
                was_successful=False,
                error_message=str(e)
            )
        
    async def get_all_rates(self, base: str) -> APICallResult:
        """
        Get all rates for a particular base currency
        Default is base currency is USD, seee https://currencyapi.com/docs/latest for more info.
        """
        start_time = datetime.now(tz=UTC)

        try:
            response = self.sdk_client.latest(base_currency=base)
            data = response["data"]
            last_updated = response["meta"]["last_updated_at"]
            timestamp = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            

            rates = [
                ExchangeRateResponse(
                    base_currency=base,
                    target_currency=info["code"],
                    rate=info["value"],
                    timestamp=timestamp,
                    provider_name=self.name,
                    raw_response=response
                )
                for _, info in data.items()
            ]

            return APICallResult(
                provider_name=self.name,
                endpoint="latest",
                http_status_code=200,
                response_time_ms=int((datetime.now(tz=UTC) - start_time).total_seconds() * 1000),
                was_successful=True,
                data=rates,
                raw_response=response
            )
        
        except Exception as e:
            return APICallResult(
                provider_name=self.name,
                endpoint="latest",
                http_status_code=None,
                response_time_ms=int((datetime.now(tz=UTC) - start_time).total_seconds() * 1000),
                was_successful=False,
                error_message=str(e)
            )

    async def get_supported_currencies(self) -> APICallResult:
        """Get supported currencies from CurrencyAPI"""
        start_time = datetime.now(tz=UTC)

        try:
            response = self.sdk_client.currencies()
            logger.info("Fetching list of supported currencies using CurrencyAPI SDK")

            symbols = list(response["data"].keys())

            return APICallResult(
                provider_name=self.name,
                endpoint="currencies",
                http_status_code=200,
                response_time_ms=int((datetime.now(tz=UTC) - start_time).total_seconds() * 1000),
                was_successful=True,
                data=symbols,
                raw_response=response
            )

        except Exception as e:
            logger.error("Error fetching supported currencies using CurrencyAPI SDK")
            return APICallResult(
                provider_name=self.name,
                endpoint="currencies",
                http_status_code=None,
                response_time_ms=int((datetime.now(tz=UTC) - start_time).total_seconds() * 1000),
                was_successful=False,
                error_message=str(e)
            )