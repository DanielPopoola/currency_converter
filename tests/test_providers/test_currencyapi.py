
"""
Tests for the CurrencyAPI provider implementation.
"""
import os
import pytest
from unittest.mock import patch, Mock
from decimal import Decimal
import urllib.parse
import httpx

from app.providers import CurrencyAPIProvider, ExchangeRateResponse
from .fixtures.api_responses import CURRENCYAPI_RESPONSES
from .conftest import assert_exchange_rate_response, assert_api_call_result, currencyapi_provider


class TestCurrencyAPIProviderInitialization:
    """Test CurrencyAPI provider initialization"""

    def test_provider_initialization_with_env_var(self):
        """Test provider initializes correctly with environment variable"""
        with patch.dict('os.environ', {'CURRENCYAPI_KEY': 'test_key_123'}):
            provider = CurrencyAPIProvider(api_key=os.environ['CURRENCYAPI_KEY'])

            assert provider.api_key == 'test_key_123'
            assert provider.base_url == 'https://api.currencyapi.com/v3'
            assert provider.name == 'CurrencyAPI'
            assert provider.timeout == 3


class TestCurrencyAPIURLBuilding:
    """Test CurrencyAPI-specific URL building logic"""

    def test_build_request_url_basic(self, currencyapi_provider):
        """Test basic URL building"""
        params = {'base_currency': 'USD', 'currencies': 'EUR'}
        url = currencyapi_provider._build_request_url('latest', params)

        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)

        assert parsed.scheme == 'https'
        assert parsed.netloc == 'api.currencyapi.com'
        assert parsed.path == '/v3/latest'
        assert 'api_key' in query_params
        assert query_params['base_currency'] == ['USD']
        assert query_params['currencies'] == ['EUR']


class TestCurrencyAPIResponseParsing:
    """Test CurrencyAPI-specific response parsing logic"""

    def test_parse_successful_response(self, currencyapi_provider):
        """Test parsing a successful CurrencyAPI response"""
        response_data = CURRENCYAPI_RESPONSES["single_rate_success"]

        result = currencyapi_provider._parse_rate_response(response_data, "USD", "EUR")

        assert_exchange_rate_response(result, "USD", "EUR", Decimal("0.85432"))
        assert result.is_successful is True
        assert result.provider_name == "CurrencyAPI"
        assert result.raw_response == response_data


class TestCurrencyAPIGetExchangeRate:
    """Test the get_exchange_rate method"""

    @pytest.mark.asyncio
    async def test_get_exchange_rate_success(self, currencyapi_provider):
        """Test successful single rate retrieval"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = CURRENCYAPI_RESPONSES["single_rate_success"]

        with patch.object(currencyapi_provider.client, 'get', return_value=mock_response):
            result = await currencyapi_provider.get_exchange_rate("USD", "EUR")

            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, ExchangeRateResponse)
            assert result.data.base_currency == "USD"
            assert result.data.target_currency == "EUR"
            assert result.data.rate == Decimal("0.85432")

    @pytest.mark.asyncio
    async def test_get_exchange_rate_api_error(self, currencyapi_provider):
        """Test handling CurrencyAPI API errors"""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = CURRENCYAPI_RESPONSES["api_error"]["message"]
        error = httpx.HTTPStatusError(message="", request=Mock(), response=mock_response)

        with patch.object(currencyapi_provider.client, 'get', side_effect=error):
            result = await currencyapi_provider.get_exchange_rate("USD", "EUR")

            assert result.was_successful is False
            assert "HTTP 403" in result.error_message

class TestCurrencyAPIGetAllRates:
    """Test the get_all_rates method"""

    @pytest.mark.asyncio
    async def test_get_all_rates_success(self, currencyapi_provider):
        """Test successful retrieval of all rates"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = CURRENCYAPI_RESPONSES["all_rates_success"]

        with patch.object(currencyapi_provider.client, 'get', return_value=mock_response):
            result = await currencyapi_provider.get_all_rates("USD")

            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, list)
            assert len(result.data) == 4

            for rate_response in result.data:
                assert isinstance(rate_response, ExchangeRateResponse)
                assert rate_response.base_currency == "USD"
                assert rate_response.is_successful is True

class TestCurrencyAPIGetSupportedCurrencies:
    """Test the get_supported_currencies method"""

    @pytest.mark.asyncio
    async def test_get_supported_currencies_success(self, currencyapi_provider):
        """Test successful retrieval of supported currencies"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = CURRENCYAPI_RESPONSES["currencies_success"]

        with patch.object(currencyapi_provider.client, 'get', return_value=mock_response):
            result = await currencyapi_provider.get_supported_currencies()

            assert_api_call_result(result, expected_success=True)
            assert isinstance(result.data, list)
            assert "USD" in result.data
            assert "EUR" in result.data
