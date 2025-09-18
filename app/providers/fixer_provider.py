import os
import logging
import urllib.parse
from typing import Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from .base_provider import APIProvider, APICallResult, ExchangeRateResponse


class FixerIOProvider(APIProvider):
    """Primary provider implementation"""

    def __init__(self):
        super().__init__(
            api_key = os.getenv("FIXER_IO_API_KEY", "api_key"),
            base_url="http://data.fixer.io/api/",
            name="fixer.io",
            timeout=3
        )

    def _build_request_url(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Build Fixer.IO  url with API key authentication"""
        params['access_key'] = self.api_key

        return f"{self.base_url}{endpoint}?{urllib.parse.urlencode(params)}"
    
    def _parse_rate_response(self, response_data: Dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        """Parse Fixer.IO response format"""
        try:
            if not response_data.get('success', False):
                error_msg = response_data.get('error', {}).get('info', 'Unknown API error')
                return ExchangeRateResponse(
                    base_currency=base,
                    target_currency=target,
                    rate=0.0,
                    timestamp=datetime.now(),
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
                    rate=0.0,
                    timestamp=datetime.now(),
                    provider_name=self.name,
                    raw_response=response_data,
                    is_successful=False,
                    error_message=f"Target currency {target} not found in rates"
                )
            
            # Convert timestamp if provided
            api_timestamp = response_data.get('timestamp')
            if api_timestamp:
                timestamp = datetime.fromtimestamp(api_timestamp, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            return ExchangeRateResponse(
                base_currency=base,
                target_currency=target,
                rate=float(rates[target]),
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
                timestamp=datetime.now(),
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

        result = await self._make_request('latest', params)

        if result.was_successful and result.raw_response:
            # Parse the response into standardized format
            parsed_response = self._parse_rate_response(result.raw_response, base, target)
            result.data = parsed_response
            result.was_successful = parsed_response.is_successful
            if not parsed_response.is_successful:
                result.error_message = parsed_response.error_message

        return result
    
    async def get_all_rates(self, base: str) -> APICallResult:
        """Get all rates for base currency from Fixer.io"""
        params = {'base': base}
        result = await self._make_request('latest', params)

        if result.was_successful and result.raw_response:
            try:
                rates_data = result.raw_response.get('rates', {})
                if not rates_data:
                    result.was_successful = False
                    result.error_message = "No rate found in response"
                    return result
                

                api_timestamp = result.raw_response.get('timestamp')
                timestamp = datetime.fromtimestamp(api_timestamp) if api_timestamp else datetime.now()

                responses = []
                for target, rate in rates_data.items():
                        responses.append(
                            ExchangeRateResponse(
                                base_currency=base,
                                target_currency=target,
                                rate=float(rate),
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

        if result.was_successful and result.raw_response:
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