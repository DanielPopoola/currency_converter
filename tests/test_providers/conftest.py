"""
Shared test configuration and fixtures for provider tests.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, UTC

from app.providers import FixerIOProvider, OpenExchangeProvider, CurrencyAPIProvider
from .fixtures.api_responses import (
    FIXERIO_RESPONSES, 
    OPENEXCHANGE_RESPONSES, 
    CURRENCYAPI_RESPONSES,
    NETWORK_ERROR_SCENARIOS
)

# Test Configuration
TEST_API_KEY = "test_api_key_12345"
TEST_TIMEOUT = 3

@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing"""
    with patch.dict('os.environ', {
        'FIXERIO_API_KEY': TEST_API_KEY,
        'OPENEXCHANGE_APP_ID': TEST_API_KEY,
        'CURRENCYAPI_KEY': TEST_API_KEY
    }):
        yield

@pytest.fixture
def fixerio_provider(mock_env_vars):
    """Create FixerIO provider instance for testing"""
    return FixerIOProvider(mock_env_vars)


@pytest.fixture
def openexchange_provider(mock_env_vars):
    """Create OpenExchange provider instance for testing"""
    return OpenExchangeProvider(mock_env_vars)


@pytest.fixture
def currencyapi_provider(mock_env_vars):
    """Create CurrencyAPI provider instance for testing"""
    return CurrencyAPIProvider(mock_env_vars)

@pytest.fixture
def all_providers(fixerio_provider, openexchange_provider, currencyapi_provider):
    """All provider instances for parametrized tests"""
    return [fixerio_provider, openexchange_provider, currencyapi_provider]


class MockResponse:
    """Mock HTTP response for testing"""
    def __init__(self, json_data, status_code=200, text=None):
        self.json_data = json_data
        self.status_code = status_code
        self.text = text or str(json_data)
    
    def json(self):
        if isinstance(self.json_data, Exception):
            raise self.json_data
        return self.json_data
    
@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient for testing"""
    mock_client = AsyncMock()
    
    def create_mock_response(json_data, status_code=200):
        return MockResponse(json_data, status_code)
    
    # Helper function to set up responses
    mock_client.create_response = create_mock_response
    return mock_client


@pytest.fixture
def mock_successful_response():
    """Standard successful HTTP response"""
    return MockResponse({"test": "data"}, 200)


@pytest.fixture
def mock_timeout_response():
    """Mock timeout exception"""
    return httpx.TimeoutException("Request timed out")


@pytest.fixture  
def mock_connection_error():
    """Mock connection error"""
    return httpx.ConnectError("Failed to connect")


# Response fixtures for each provider
@pytest.fixture
def fixerio_single_rate_response():
    return MockResponse(FIXERIO_RESPONSES["single_rate_success"])


@pytest.fixture
def fixerio_all_rates_response():
    return MockResponse(FIXERIO_RESPONSES["all_rates_success"])


@pytest.fixture
def fixerio_error_response():
    return MockResponse(FIXERIO_RESPONSES["api_error"])


@pytest.fixture
def openexchange_single_rate_response():
    return MockResponse(OPENEXCHANGE_RESPONSES["single_rate_success"])


@pytest.fixture
def currencyapi_single_rate_response():
    return MockResponse(CURRENCYAPI_RESPONSES["single_rate_success"])


# Test data sets for parametrized tests
CURRENCY_PAIRS = [
    ("USD", "EUR"),
    ("EUR", "USD"), 
    ("GBP", "JPY"),
    ("CAD", "AUD")
]

INVALID_CURRENCY_PAIRS = [
    ("XXX", "EUR"),  # Invalid base
    ("USD", "YYY"),  # Invalid target
    ("", "EUR"),     # Empty base
    ("USD", ""),     # Empty target
]

BASE_CURRENCIES = ["USD", "EUR", "GBP", "JPY"]

@pytest.fixture(params=CURRENCY_PAIRS)
def currency_pair(request):
    """Parametrized currency pairs for testing"""
    return request.param


@pytest.fixture(params=BASE_CURRENCIES)  
def base_currency(request):
    """Parametrized base currencies for testing"""
    return request.param


# Assertion helpers
def assert_exchange_rate_response(response, base, target, expected_rate=None):
    """Helper to assert ExchangeRateResponse properties"""
    assert response.base_currency == base
    assert response.target_currency == target
    assert isinstance(response.rate, float)
    assert isinstance(response.timestamp, datetime)
    assert response.provider_name is not None
    assert response.raw_response is not None
    
    if expected_rate:
        assert abs(response.rate - expected_rate) < 0.0001  # Float comparison


def assert_api_call_result(result, expected_success=True, expected_status=200):
    """Helper to assert APICallResult properties"""
    assert isinstance(result.response_time_ms, int)
    assert result.response_time_ms >= 0
    assert result.was_successful == expected_success
    assert result.provider_name is not None
    assert result.endpoint is not None
    
    if expected_success:
        assert result.http_status_code == expected_status
        assert result.error_message is None
    else:
        assert result.error_message is not None


# Async test utilities
@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Custom markers for different test types
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests") 
    config.addinivalue_line("markers", "slow: Slow tests that hit real APIs")
    config.addinivalue_line("markers", "network: Tests requiring network access")
