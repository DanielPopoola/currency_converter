import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .base import APICallResult, APIProvider, ExchangeRateResponse


class FixerIOProvider(APIProvider):
    """Primary provider implementation"""

    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="http://data.fixer.io/api/",
            name="FixerIO",
            timeout=3
        )

    def _build_request_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build Fixer.IO  url with API key authentication"""
        params['access_key'] = self.api_key

        return f"{self.base_url.rstrip('/')}/{endpoint}?{urllib.parse.urlencode(params)}"
    
    def _parse_rate_response(self, response_data: dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        """Parse Fixer.IO response format"""
        try:
            if not response_data.get('success', False):
                error_msg = response_data.get('error', {}).get('info', 'Unknown API error')
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
                    timestamp=datetime.now(UTC),
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
            self.logger.error(
                "Failed to parse {provider_name} response: {error}",
                provider_name=self.name,
                error=str(e),
                raw_response=response_data,
                event_type="API_CALL",
                timestamp=datetime.now()
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
        """Get single currency pair from Fixer.IO"""
        params = {
            'base': base,
            'symbols': target
        }

        # _make_request will raise an exception on HTTP failure
        result = await self._make_request('latest', params)

        # If we get here, the HTTP call was successful. Now, parse the payload.
        parsed_response = self._parse_rate_response(result.raw_response, base, target)
        result.data = parsed_response
        
        # The API can return a "successful" response that contains an error message (e.g. invalid currency)
        # We update the result's success status based on the parsed payload.
        result.was_successful = parsed_response.is_successful
        if not parsed_response.is_successful:
            result.error_message = parsed_response.error_message

        return result
    
    async def get_all_rates(self, base: str) -> APICallResult:
        """Get all rates for base currency from Fixer.io"""
        params = {'base': base}
        result = await self._make_request('latest', params)

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
        """Get supported currencies from Fixer.io"""
        result = await self._make_request('symbols', {})

        try:
            symbols = result.raw_response.get('symbols', {})
            if not symbols:
                result.was_successful = False
                result.error_message = "No symbols found in response"
            else:
                result.data = list(symbols.keys())
        except Exception as e:
            result.was_successful = False
            result.error_message = f"Failed to process symbols: {str(e)}"
        
        return result
