
"""
Tests for the OpenExchange provider implementation.
"""
import os
import pytest
from unittest.mock import patch, Mock
from datetime import datetime, UTC
import urllib.parse

from app.providers import OpenExchangeProvider, ExchangeRateResponse, APICallResult
from .fixtures.api_responses import OPENEXCHANGE_RESPONSES
from .conftest import assert_exchange_rate_response, assert_api_call_result, openexchange_provider


class TestOpenExchangeProviderInitialization:
    """Test OpenExchange provider initialization"""

    def test_provider_initialization_with_env_var(self):
        """Test provider initializes correctly with environment variable"""
        with patch.dict('os.environ', {'OPENEXCHANGE_APP_ID': 'test_key_123'}):
            provider = OpenExchangeProvider(api_key=os.environ['OPENEXCHANGE_APP_ID'])

            assert provider.api_key == 'test_key_123'
            assert provider.base_url == 'https://openexchangerates.org/api'
            assert provider.name == 'OpenExchange'
            assert provider.timeout == 3


class TestOpenExchangeURLBuilding:
    """Test OpenExchange-specific URL building logic"""

    def test_build_request_url_basic(self, openexchange_provider):
        """Test basic URL building"""
        params = {'base': 'USD', 'symbols': 'EUR'}
        url = openexchange_provider._build_request_url('latest.json', params)

        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)

        assert parsed.scheme == 'https'
        assert parsed.netloc == 'openexchangerates.org'
        assert parsed.path == '/api/latest.json'
        assert 'app_id' in query_params
        assert query_params['base'] == ['USD']
        assert query_params['symbols'] == ['EUR']


class TestOpenExchangeResponseParsing:
    """Test OpenExchange-specific response parsing logic"""

    def test_parse_successful_response(self, openexchange_provider):
        """Test parsing a successful OpenExchange response"""
        response_data = OPENEXCHANGE_RESPONSES["single_rate_success"]

        result = openexchange_provider._parse_rate_response(response_data, "USD", "EUR")

        assert_exchange_rate_response(result, "USD", "EUR", 0.85432)
        assert result.is_successful is True
        assert result.provider_name == "OpenExchange"
        assert result.raw_response == response_data


class TestOpenExchangeGetExchangeRate:
    """Test the get_exchange_rate method"""

    @pytest.mark.asyncio
    async def test_get_exchange_rate_success(self, openexchange_provider):
        """Test successful single rate retrieval"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = OPENEXCHANGE_RESPONSES["single_rate_success"]

        with patch.object(openexchange_provider.client, 'get', return_value=mock_response):
            result = await openexchange_provider.get_exchange_rate("USD", "EUR")

            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, ExchangeRateResponse)
            assert result.data.base_currency == "USD"
            assert result.data.target_currency == "EUR"
            assert result.data.rate == 0.85432

    @pytest.mark.asyncio
    async def test_get_exchange_rate_api_error(self, openexchange_provider):
        """Test handling OpenExchange API errors"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = OPENEXCHANGE_RESPONSES["api_error"]

        with patch.object(openexchange_provider.client, 'get', return_value=mock_response):
            result = await openexchange_provider.get_exchange_rate("USD", "EUR")

            assert result.http_status_code == 200
            assert result.was_successful is False
            assert "Invalid App ID provided" in result.error_message
            assert isinstance(result.data, ExchangeRateResponse)
            assert result.data.is_successful is False

class TestOpenExchangeGetAllRates:
    """Test the get_all_rates method"""

    @pytest.mark.asyncio
    async def test_get_all_rates_success(self, openexchange_provider):
        """Test successful retrieval of all rates"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = OPENEXCHANGE_RESPONSES["all_rates_success"]

        with patch.object(openexchange_provider.client, 'get', return_value=mock_response):
            result = await openexchange_provider.get_all_rates("USD")

            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, list)
            assert len(result.data) == 4

            for rate_response in result.data:
                assert isinstance(rate_response, ExchangeRateResponse)
                assert rate_response.base_currency == "USD"
                assert rate_response.is_successful is True

class TestOpenExchangeGetSupportedCurrencies:
    """Test the get_supported_currencies method"""

    @pytest.mark.asyncio
    async def test_get_supported_currencies_success(self, openexchange_provider):
        """Test successful retrieval of supported currencies"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = OPENEXCHANGE_RESPONSES["currencies_success"]

        with patch.object(openexchange_provider.client, 'get', return_value=mock_response):
            result = await openexchange_provider.get_supported_currencies()

            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, list)
            assert "USD" in result.data
            assert "EUR" in result.data
            assert "GBP" in result.data
            assert "JPY" in result.data
