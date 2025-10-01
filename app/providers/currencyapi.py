import logging
import os
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.monitoring.logger import EventType, LogEvent, LogLevel

from .base import APICallResult, APIProvider, ExchangeRateResponse


class CurrencyAPIProvider(APIProvider):
    """CurrencyAPI provider implementation using direct HTTP calls"""
    
    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://api.currencyapi.com/v3",
            name="CurrencyAPI",
            timeout=3,
            extra_headers={"apikey": api_key}
        )

    def _build_request_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build CurrencyAPI URL (authentication is handled by headers)"""
        return f"{self.base_url}/{endpoint}?{urllib.parse.urlencode(params)}"

    def _parse_rate_response(self, response_data: dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        """Parse CurrencyAPI response format"""
        try:
            # Check if response has expected structure
            if "data" not in response_data:
                error_msg = "Invalid response format: missing 'data' field"
                return ExchangeRateResponse(
                    base_currency=base,
                    target_currency=target,
                    rate=Decimal("0"),
                    timestamp=datetime.now(UTC),
                    provider_name=self.name,
                    raw_response=response_data,
                    is_successful=False,
                    error_message=error_msg
                )

            data = response_data["data"]
            
            # Check if target currency exists in response
            if target not in data:
                return ExchangeRateResponse(
                    base_currency=base,
                    target_currency=target,
                    rate=Decimal("0"),
                    timestamp=datetime.now(UTC),
                    provider_name=self.name,
                    raw_response=response_data,
                    is_successful=False,
                    error_message=f"Target currency {target} not found in rates"
                )

            # Extract rate information
            rate_info = data[target]
            
            # Parse timestamp from meta information
            meta = response_data.get("meta", {})
            last_updated = meta.get("last_updated_at")
            
            if last_updated:
                # CurrencyAPI returns ISO format with Z suffix
                timestamp = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(UTC)

            return ExchangeRateResponse(
                base_currency=base,
                target_currency=target,
                rate=Decimal(str(rate_info["value"])),
                timestamp=timestamp,
                provider_name=self.name,
                raw_response=response_data,
                is_successful=True
            )
        
        except Exception as e:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.API_CALL,
                    level=LogLevel.ERROR,
                    message=f"Failed to parse {self.name} response: {e}",
                    timestamp=datetime.now(UTC),
                    error_context={'error': str(e), 'raw_response': response_data}
                )
            )
            return ExchangeRateResponse(
                base_currency=base,
                target_currency=target,
                rate=Decimal("0"),
                timestamp=datetime.now(UTC),
                provider_name=self.name,
                raw_response=response_data,
                is_successful=False,
                error_message=f"Parsing error: {str(e)}"
            )

    async def get_exchange_rate(self, base: str, target: str) -> APICallResult:
        """Get single currency pair from CurrencyAPI"""
        params = {
            'base_currency': base,
            'currencies': target
        }

        result = await self._make_request('latest', params)

        # The HTTP call was successful, now parse the payload.
        parsed_response = self._parse_rate_response(result.raw_response, base, target)
        result.data = parsed_response
        result.was_successful = parsed_response.is_successful
        if not parsed_response.is_successful:
            result.error_message = parsed_response.error_message

        return result

    async def get_all_rates(self, base: str = "USD") -> APICallResult:
        """Get all rates for base currency from CurrencyAPI"""
        params = {'base_currency': base}
        result = await self._make_request('latest', params)

        try:
            data = result.raw_response.get("data", {})
            if not data:
                result.was_successful = False
                result.error_message = "No rate data found in response"
                return result

            # Parse timestamp from meta information
            meta = result.raw_response.get("meta", {})
            last_updated = meta.get("last_updated_at")
            
            if last_updated:
                timestamp = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(UTC)

            responses = []
            for target_currency, rate_info in data.items():
                responses.append(
                    ExchangeRateResponse(
                        base_currency=base,
                        target_currency=target_currency,
                        rate=Decimal(str(rate_info["value"])),
                        timestamp=timestamp,
                        provider_name=self.name,
                        raw_response=result.raw_response,
                        is_successful=True
                    )
                )
            
            result.data = responses
        except Exception as e:
            result.was_successful = False
            result.error_message = f"Failed to process rates: {str(e)}"
    
        return result

    async def get_supported_currencies(self) -> APICallResult:
        """Get supported currencies from CurrencyAPI"""
        result = await self._make_request('currencies', {})

        try:
            data = result.raw_response.get("data", {})
            if not data:
                result.was_successful = False
                result.error_message = "No currency data found in response"
            else:
                # CurrencyAPI returns currencies as {"USD": {"symbol": "$", "name": "US Dollar", "symbol_native": "$", "decimal_digits": 2, "rounding": 0, "code": "USD", "name_plural": "US dollars"}}
                result.data = list(data.keys())
        except Exception as e:
            result.was_successful = False
            result.error_message = f"Failed to process currencies: {str(e)}"
        
        return result
