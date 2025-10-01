"""
Tests for the FixerIO provider implementation.
Tests both the provider-specific logic and integration with the base class.
"""
import os
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.providers import APICallResult, ExchangeRateResponse, FixerIOProvider

from .conftest import assert_api_call_result, assert_exchange_rate_response, fixerio_provider
from .fixtures.api_responses import FIXERIO_RESPONSES


class TestFixerIOProviderInitialization:
    """Test FixerIO provider initialization"""
    
    def test_provider_initialization_with_env_var(self):
        """Test provider initializes correctly with environment variable"""
        with patch.dict('os.environ', {'FIXER_API_KEY': 'test_key_123'}):
            provider = FixerIOProvider(api_key=os.environ['FIXER_API_KEY'])
            
            assert provider.api_key == 'test_key_123'
            assert provider.base_url == 'http://data.fixer.io/api'
            assert provider.name == 'FixerIO'
            assert provider.timeout == 3
    
    def test_provider_inheritance(self):
        """Test that FixerIO provider properly inherits from APIProvider"""
        with patch.dict('os.environ', {'FIXER_API_KEY': 'test_key_123'}):
            provider = FixerIOProvider(api_key=os.environ['FIXER_API_KEY'])
        
            # Should have all the base class methods
            assert hasattr(provider, '_make_request')
            assert hasattr(provider, 'close')
            assert hasattr(provider, 'client')


class TestFixerIOURLBuilding:
    """Test FixerIO-specific URL building logic"""
    
    def test_build_request_url_basic(self, fixerio_provider):
        """Test basic URL building"""
        params = {'base': 'USD', 'symbols': 'EUR'}
        url = fixerio_provider._build_request_url('latest', params)
        
        # Parse the URL to check components
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        assert parsed.scheme == 'http'
        assert parsed.netloc == 'data.fixer.io'
        assert parsed.path == '/api/latest'
        assert 'access_key' in query_params
        assert query_params['base'] == ['USD']
        assert query_params['symbols'] == ['EUR']
    
    def test_build_request_url_with_api_key(self, fixerio_provider):
        """Test that API key is correctly added to URL"""
        fixerio_provider.api_key = "test_key_123"
        params = {'test': 'param'}
        url = fixerio_provider._build_request_url('test_endpoint', params)
    
        query_params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert query_params['access_key'][0] == fixerio_provider.api_key
    
    def test_build_request_url_empty_params(self, fixerio_provider):
        """Test URL building with empty parameters"""
        url = fixerio_provider._build_request_url('currencies', {})
        
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        # Should still have API key
        assert 'access_key' in query_params
        assert len(query_params) == 1  # Only API key
    
    def test_build_request_url_special_characters(self, fixerio_provider):
        """Test URL building handles special characters properly"""
        params = {'currency': 'USD,EUR', 'date': '2023-01-01'}
        url = fixerio_provider._build_request_url('historical', params)
        
        # Should be properly URL encoded
        assert 'USD%2CEUR' in url or 'USD,EUR' in url  # Either is acceptable
        assert '2023-01-01' in url


class TestFixerIOResponseParsing:
    """Test FixerIO-specific response parsing logic"""
    
    def test_parse_successful_response(self, fixerio_provider):
        """Test parsing a successful FixerIO response"""
        response_data = FIXERIO_RESPONSES["single_rate_success"]
        
        result = fixerio_provider._parse_rate_response(response_data, "EUR", "USD")
        
        assert_exchange_rate_response(result, "EUR", "USD", Decimal("1.23396"))
        assert result.is_successful is True
        assert result.provider_name == "FixerIO"
        assert result.raw_response == response_data
        
        # Check timestamp conversion from Unix timestamp
        expected_timestamp = datetime.fromtimestamp(1519296206, tz=UTC)
        assert result.timestamp == expected_timestamp
    
    def test_parse_api_error_response(self, fixerio_provider):
        """Test parsing FixerIO API error response"""
        response_data = FIXERIO_RESPONSES["api_error"]
        
        result = fixerio_provider._parse_rate_response(response_data, "USD", "EUR")
        
        assert result.is_successful is False
        assert result.rate == 0.0
        assert "monthly usage limit" in result.error_message
        assert result.base_currency == "USD"
        assert result.target_currency == "EUR"
    
    def test_parse_missing_target_currency(self, fixerio_provider):
        """Test parsing when target currency is missing from response"""
        response_data = FIXERIO_RESPONSES["missing_target_currency"]
        
        result = fixerio_provider._parse_rate_response(response_data, "USD", "EUR")
        
        assert result.is_successful is False
        assert "Target currency EUR not found" in result.error_message
        assert result.rate == 0.0
    
    def test_parse_response_without_timestamp(self, fixerio_provider):
        """Test parsing response without timestamp (should use current time)"""
        response_data = {
            "success": True,
            "base": "USD",
            "rates": {"EUR": 0.85}
            # No timestamp field
        }
        
        before_parsing = datetime.now(UTC)
        result = fixerio_provider._parse_rate_response(response_data, "USD", "EUR")
        after_parsing = datetime.now(UTC)
        
        assert result.is_successful is True
        assert before_parsing <= result.timestamp <= after_parsing
    
    def test_parse_malformed_response(self, fixerio_provider):
        """Test parsing completely malformed response"""
        malformed_data = {"unexpected": "structure"}
        
        result = fixerio_provider._parse_rate_response(malformed_data, "USD", "EUR")
        
        assert result.is_successful is False
        assert "Unknown API error" in result.error_message
        assert result.rate == 0.0
    
    def test_parse_response_with_string_rate(self, fixerio_provider):
        """Test parsing response where rate is a string (should convert to float)"""
        response_data = {
            "success": True,
            "timestamp": 1700870399,
            "base": "USD",
            "rates": {"EUR": "0.85432"}
        }
        
        result = fixerio_provider._parse_rate_response(response_data, "USD", "EUR")
        
        assert result.is_successful is True
        assert result.rate == Decimal("0.85432")
        assert isinstance(result.rate, Decimal)


class TestFixerIOGetExchangeRate:
    """Test the get_exchange_rate method"""
    
    @pytest.mark.asyncio
    async def test_get_exchange_rate_success(self, fixerio_provider):
        """Test successful single rate retrieval"""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = FIXERIO_RESPONSES["single_rate_success"]
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_exchange_rate("EUR", "USD")
            
            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, ExchangeRateResponse)
            assert result.data.base_currency == "EUR"
            assert result.data.target_currency == "USD"
            assert result.data.rate == Decimal("1.23396")
    
    @pytest.mark.asyncio
    async def test_get_exchange_rate_api_error(self, fixerio_provider):
        """Test handling FixerIO API errors"""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = FIXERIO_RESPONSES["api_error"]
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_exchange_rate("USD", "EUR")
            
            # HTTP call succeeded but API returned error
            assert result.http_status_code == 200
            assert result.was_successful is False
            assert "monthly usage limit" in result.error_message
            assert isinstance(result.data, ExchangeRateResponse)
            assert result.data.is_successful is False
    
    @pytest.mark.asyncio
    async def test_get_exchange_rate_http_error(self, fixerio_provider):
        """Test handling HTTP errors"""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        error = httpx.HTTPStatusError(
            "Unauthorized", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status.side_effect = error

        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError) as excinfo:
                await fixerio_provider.get_exchange_rate("USD", "EUR")
            
            assert excinfo.value.response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_exchange_rate_request_parameters(self, fixerio_provider):
        """Test that correct parameters are sent to API"""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = FIXERIO_RESPONSES["single_rate_success"]
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response) as mock_get:
            await fixerio_provider.get_exchange_rate("GBP", "JPY")
            
            # Check that the correct URL was called
            called_url = mock_get.call_args[0][0]
            parsed = urllib.parse.urlparse(called_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            
            assert query_params['base'] == ['GBP']
            assert query_params['symbols'] == ['JPY']
            assert 'access_key' in query_params


class TestFixerIOGetAllRates:
    """Test the get_all_rates method"""
    
    @pytest.mark.asyncio
    async def test_get_all_rates_success(self, fixerio_provider):
        """Test successful retrieval of all rates"""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = FIXERIO_RESPONSES["all_rates_success"]
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_all_rates("EUR")
            
            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, list)
            assert len(result.data) == 7
            
            # Check each rate response
            for rate_response in result.data:
                assert isinstance(rate_response, ExchangeRateResponse)
                assert rate_response.base_currency == "EUR"
                assert rate_response.is_successful is True
    
    @pytest.mark.asyncio
    async def test_get_all_rates_empty_response(self, fixerio_provider):
        """Test handling empty rates in response"""
        empty_response = {
            "success": True,
            "timestamp": 1700870399,
            "base": "USD",
            "rates": {}  # Empty rates
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = empty_response
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_all_rates("USD")
            
            assert result.was_successful is False
            assert "No rate found" in result.error_message
    
    @pytest.mark.asyncio
    async def test_get_all_rates_processing_error(self, fixerio_provider):
        """Test handling of processing errors in get_all_rates"""
        # Response that will cause processing error
        malformed_response = {
            "success": True,
            "timestamp": "invalid_timestamp",  # This will cause parsing error
            "base": "USD", 
            "rates": {"EUR": 0.85}
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = malformed_response
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_all_rates("USD")
            
            assert result.was_successful is False
            assert "Failed to process rates" in result.error_message


class TestFixerIOGetSupportedCurrencies:
    """Test the get_supported_currencies method"""
    
    @pytest.mark.asyncio
    async def test_get_supported_currencies_success(self, fixerio_provider):
        """Test successful retrieval of supported currencies"""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = FIXERIO_RESPONSES["currencies_success"]
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_supported_currencies()
            
            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, list)
            assert "USD" in result.data
            assert "EUR" in result.data
            assert "GBP" in result.data
            assert "JPY" in result.data
    
    @pytest.mark.asyncio
    async def test_get_supported_currencies_empty_response(self, fixerio_provider):
        """Test handling empty symbols response"""
        empty_response = {
            "success": True,
            "symbols": {}
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = empty_response
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_supported_currencies()
            
            assert result.was_successful is False
            assert "No symbols found" in result.error_message
    
    @pytest.mark.asyncio
    async def test_get_supported_currencies_processing_error(self, fixerio_provider):
        """Test handling processing errors in get_supported_currencies"""
        # This will cause a processing error when trying to access .keys()
        malformed_response = {
            "success": True,
            "symbols": "not_a_dict"  # Should be a dict
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = malformed_response
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_supported_currencies()
            
            assert result.was_successful is False
            assert "Failed to process symbols" in result.error_message


class TestFixerIOIntegration:
    """Integration tests that test the full flow"""
    
    @pytest.mark.asyncio
    async def test_full_exchange_rate_flow(self, fixerio_provider):
        """Test complete flow from request to parsed response"""
        # This test simulates the complete flow:
        # 1. Build URL with parameters
        # 2. Make HTTP request  
        # 3. Parse response
        # 4. Return standardized result
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = FIXERIO_RESPONSES["single_rate_success"]
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response) as mock_get:
            result = await fixerio_provider.get_exchange_rate("EUR", "USD")
            
            # Verify the complete flow worked
            assert result.was_successful is True
            assert isinstance(result.data, ExchangeRateResponse)
            assert result.data.rate == Decimal("1.23396")
            
            # Verify URL was built correctly
            called_url = mock_get.call_args[0][0]
            assert "latest" in called_url
            assert "base=EUR" in called_url
            assert "symbols=USD" in called_url
            assert "access_key" in called_url


class TestFixerIOParametrized:
    """Parametrized tests for different currency combinations"""
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("base,target", [
        ("USD", "EUR"),
        ("EUR", "USD"),
        ("GBP", "JPY"),
        ("CAD", "AUD"),
    ])
    async def test_exchange_rate_different_currencies(self, fixerio_provider, base, target):
        """Test exchange rate retrieval with different currency pairs"""
        # Create response for any currency pair
        response_data = {
            "success": True,
            "timestamp": 1700870399,
            "base": base,
            "rates": {target: 1.23456}
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_exchange_rate(base, target)
            
            assert result.was_successful is True
            assert result.data.base_currency == base
            assert result.data.target_currency == target
            assert result.data.rate == Decimal("1.23456")
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("base_currency", ["USD", "EUR", "GBP", "JPY"])
    async def test_all_rates_different_bases(self, fixerio_provider, base_currency):
        """Test get_all_rates with different base currencies"""
        response_data = {
            "success": True,
            "timestamp": 1700870399,
            "base": base_currency,
            "rates": {"EUR": 0.85, "USD": 1.17, "GBP": 0.79}
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_all_rates(base_currency)
            
            assert result.was_successful is True
            assert len(result.data) == 3
            for rate_response in result.data:
                assert rate_response.base_currency == base_currency


# Performance and edge case tests
class TestFixerIOEdgeCases:
    """Test edge cases and unusual scenarios"""
    
    @pytest.mark.asyncio
    async def test_very_large_rate_values(self, fixerio_provider):
        """Test handling very large exchange rates (like some currencies vs Japanese Yen)"""
        response_data = {
            "success": True,
            "timestamp": 1700870399,
            "base": "USD",
            "rates": {"JPY": 149.756789123}  # Large rate value
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_exchange_rate("USD", "JPY")
            
            assert result.was_successful is True
            assert result.data.rate == Decimal("149.756789123")
    
    @pytest.mark.asyncio
    async def test_very_small_rate_values(self, fixerio_provider):
        """Test handling very small exchange rates"""
        response_data = {
            "success": True,
            "timestamp": 1700870399,
            "base": "USD", 
            "rates": {"SOME_CRYPTO": 0.00000123}  # Very small rate
        }
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        
        with patch.object(fixerio_provider.client, 'get', return_value=mock_response):
            result = await fixerio_provider.get_exchange_rate("USD", "SOME_CRYPTO")
            
            assert result.was_successful is True
            assert result.data.rate == Decimal("0.00000123")