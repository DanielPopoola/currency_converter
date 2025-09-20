import os
import logging
import urllib.parse
from datetime import datetime, UTC
from typing import Any, Dict

from .base import APIProvider, ExchangeRateResponse, APICallResult

logger = logging.getLogger(__name__)


class CurrencyAPIProvider(APIProvider):
    """CurrencyAPI provider implementation using direct HTTP calls"""
    
    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://api.currencyapi.com/v3",
            name="CurrencyAPI",
            timeout=3
        )

    def _build_request_url(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Build CurrencyAPI URL with API key authentication"""
        params['apikey'] = self.api_key
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
                    rate=0.0,
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
                    rate=0.0,
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
                rate=float(rate_info["value"]),
                timestamp=timestamp,
                provider_name=self.name,
                raw_response=response_data,
                is_successful=True
            )
        
        except Exception as e:
            logger.error(f"Failed to parse {self.name} response: {e}")
            return ExchangeRateResponse(
                base_currency=base,
                target_currency=target,
                rate=0.0,
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

        if result.was_successful and result.raw_response:
            # Parse the response into standardized format
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

        if result.was_successful and result.raw_response:
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
                            rate=float(rate_info["value"]),
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

        if result.was_successful and result.raw_response:
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