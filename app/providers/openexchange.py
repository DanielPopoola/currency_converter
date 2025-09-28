import logging
import os
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

from .base import APICallResult, APIProvider, ExchangeRateResponse


class OpenExchangeProvider(APIProvider):
    """Secondary provider implementation"""

    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://openexchangerates.org/api",
            name="OpenExchange",
            timeout=3
        )

    def _build_request_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build OpenExchange url with API key authentication"""
        params['app_id'] = self.api_key

        return f"{self.base_url}/{endpoint}?{urllib.parse.urlencode(params)}"
    
    def _parse_rate_response(self, response_data: dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        """Parse OpenExchange response format"""
        try:
            if response_data.get('error'):
                error_msg = response_data.get('description', 'Unknown API error')
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
            
            rates = response_data.get('rates', {})
            if target not in rates:
                return ExchangeRateResponse(
                    base_currency=base,
                    target_currency=target,
                    rate=Decimal("0"),
                    timestamp=datetime.now(),
                    provider_name=self.name,
                    raw_response=response_data,
                    is_successful=False,
                    error_message=f"Target currency {target} not found in rates"
                )
            
            # Convert timestamp if provided
            api_timestamp = response_data.get('timestamp')
            if api_timestamp:
                timestamp = datetime.fromtimestamp(api_timestamp, tz=UTC)
            else:
                timestamp = datetime.now(UTC)

            return ExchangeRateResponse(
                base_currency=base,
                target_currency=target,
                rate=Decimal(str(rates[target])),
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
                rate=Decimal("0"),
                timestamp=datetime.now(UTC),
                provider_name=self.name,
                raw_response=response_data,
                is_successful=False,
                error_message=f"Parsing error: {str(e)}"
            )
        
    async def get_exchange_rate(self, base: str, target: str) -> APICallResult:
        """Get single currency pair from OpenExchange"""
        params = {
            'base': base,
            'symbols': target
        }

        result = await self._make_request('latest.json', params)

        if result.was_successful and result.raw_response:
            # Parse the response into standardized format
            parsed_response = self._parse_rate_response(result.raw_response, base, target)
            result.data = parsed_response
            result.was_successful = parsed_response.is_successful
            if not parsed_response.is_successful:
                result.error_message = parsed_response.error_message

        return result
    
    async def get_all_rates(self, base: str = "USD") -> APICallResult:
        """
        Get all rates for base currency from OpenExchange default is USD
        Can't change base currency now current plan is Free tier,
        See https://docs.openexchangerates.org/reference/set-base-currency for more info
        """
        params = {'base': base}
        result = await self._make_request('latest.json', params)

        if result.was_successful and result.raw_response:
            try:
                rates_data = result.raw_response.get('rates', {})
                if not rates_data:
                    result.was_successful = False
                    result.error_message = "No rate found in response"
                    return result
                

                api_timestamp = result.raw_response.get('timestamp')
                timestamp = datetime.fromtimestamp(api_timestamp, tz=UTC) if api_timestamp else datetime.now(UTC)

                responses = []
                for target, rate in rates_data.items():
                        responses.append(
                            ExchangeRateResponse(
                                base_currency=base,
                                target_currency=target,
                                rate=Decimal(str(rate)),
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
        """Get supported currencies from OpenExchange"""
        result = await self._make_request('currencies.json', {})

        if result.was_successful and result.raw_response:
            try:
                symbols = list(result.raw_response.keys())
                if not symbols:
                    result.was_successful = False
                    result.error_message = "No symbols found in response"
                else:
                    result.data = symbols
            except Exception as e:
                result.was_successful = False
                result.error_message = f"Failed to process symbols: {str(e)}"
        
        return result