"""
Tests for the abstract base APIProvider class.
These tests ensure our foundation works correctly.
"""

from typing import Any
import pytest
import pytest_asyncio
import httpx
import urllib.parse
from unittest.mock import AsyncMock, patch, Mock
from datetime import datetime, UTC


from app.providers.base import APIProvider, APICallResult, ExchangeRateResponse


class ConcreteProvider(APIProvider):
    """Concrete implementation for testing the abstract base class."""

    def __init__(self):
        super().__init__(
            api_key="test_key",
            base_url="https://api.example.com",
            name="TestProvider",
            timeout=3
        )

    def _build_request_url(self, endpoint: str, params: dict[str, Any]) -> str:
        return f"{self.base_url}/{endpoint}?api_key={self.api_key}"
    
    def _parse_rate_response(self, response_data: dict[str, Any], base: str, target: str) -> ExchangeRateResponse:
        return ExchangeRateResponse(
            base_currency=base,
            target_currency=target,
            rate=1.0,
            timestamp=datetime.now(),
            provider_name=self.name,
            raw_response=response_data
        )
    
    async def get_exchange_rate(self, base: str, target: str) -> APICallResult:
        return await self._make_request("latest", {"base": base, "target": target})
    
    async def get_all_rates(self, base: str) -> APICallResult:
        return await self._make_request("latest", {"base": base})
    
    async def get_supported_currencies(self) -> APICallResult:
        return await self._make_request("currencies", {})

class TestAPIProviderInitialization:
    """Test provider initialization and configuration"""
    
    def test_provider_initialization(self):
        """Test provider initializes with correct properties"""
        provider = ConcreteProvider()
        
        assert provider.api_key == "test_key"
        assert provider.base_url == "https://api.example.com"
        assert provider.name == "TestProvider"
        assert provider.timeout == 3
        assert provider.client is not None
         
    def test_http_client_configuration(self):
        """Test that httpx client is configured correctly"""
        provider = ConcreteProvider()
        
        # Check client is AsyncClient
        assert isinstance(provider.client, httpx.AsyncClient)
        
        # Check timeout configuration
        assert provider.client.timeout.read == 3
        
        # Check headers
        assert provider.client.headers.get("accept") == "application/json"


class TestAPIProviderHttpCalls:
    """Test the _make_request method which handles all HTTP calls"""
    
    @pytest.mark.asyncio
    async def test_successful_request(self):
        """Test successful HTTP request"""
        provider = ConcreteProvider()
        
        # The response object itself is synchronous
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"test": "data"}
        
        # Patch the async 'get' method to return our sync mock response
        with patch.object(provider.client, 'get', return_value=mock_response) as mock_get:
            result = await provider._make_request("test_endpoint", {"param": "value"})
            
            mock_get.assert_called_once_with("https://api.example.com/test_endpoint?api_key=test_key")
            mock_response.raise_for_status.assert_called_once()
            
            assert result.was_successful is True
            assert result.http_status_code == 200
            assert result.raw_response == {"test": "data"}

    @pytest.mark.asyncio
    async def test_http_error_response(self):
        """Test handling of HTTP error responses (4xx, 5xx)"""
        provider = ConcreteProvider()
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        error = httpx.HTTPStatusError(
            "Not Found", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status.side_effect = error
        
        with patch.object(provider.client, 'get', return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                await provider._make_request("missing_endpoint")
            
            mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio 
    async def test_timeout_error(self):
        """Test handling of request timeouts"""
        provider = ConcreteProvider()
        
        with patch.object(provider.client, 'get', side_effect=httpx.TimeoutException("Timeout")):
            with pytest.raises(httpx.TimeoutException):
                await provider._make_request("slow_endpoint")
    
    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Test handling of connection errors"""  
        provider = ConcreteProvider()
        
        connection_error = httpx.ConnectError("Failed to connect")
        with patch.object(provider.client, 'get', side_effect=connection_error):
            with pytest.raises(httpx.ConnectError):
                await provider._make_request("unreachable_endpoint")
    
    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """Test handling of unexpected exceptions"""
        provider = ConcreteProvider()
        
        with patch.object(provider.client, 'get', side_effect=ValueError("Unexpected error")):
            with pytest.raises(ValueError):
                await provider._make_request("error_endpoint")


class TestAPIProviderResponseTiming:
    """Test that response timing is measured correctly"""
    
    @pytest.mark.asyncio
    async def test_response_timing_measurement(self):
        """Test that response time is measured and reasonable"""
        provider = ConcreteProvider()
        
        async def mock_get_with_delay(url):
            import asyncio
            await asyncio.sleep(0.01)  # 10ms delay
            response = Mock(spec=httpx.Response)
            response.status_code = 200
            response.json.return_value = {"data": "test"}
            return response
        
        with patch.object(provider.client, 'get', side_effect=mock_get_with_delay):
            result = await provider._make_request("test")
            
            assert 5 <= result.response_time_ms <= 100


class TestAPIProviderCleanup:
    """Test resource cleanup"""
    
    @pytest.mark.asyncio
    async def test_client_cleanup(self):
        """Test that HTTP client is properly closed"""
        provider = ConcreteProvider()
        
        with patch.object(provider.client, 'aclose') as mock_close:
            await provider.close()
            mock_close.assert_called_once()


class TestExchangeRateResponse:
    """Test the ExchangeRateResponse dataclass"""
    
    def test_successful_response_creation(self):
        """Test creating a successful response"""
        response = ExchangeRateResponse(
            base_currency="USD",
            target_currency="EUR",
            rate=0.85,
            timestamp=datetime.now(),
            provider_name="TestProvider",
            raw_response={"test": "data"}
        )
        
        assert response.base_currency == "USD"
        assert response.target_currency == "EUR"
        assert response.rate == 0.85
        assert response.is_successful is True
        assert response.error_message is None
    
    def test_error_response_creation(self):
        """Test creating an error response"""
        response = ExchangeRateResponse(
            base_currency="USD",
            target_currency="EUR", 
            rate=0.0,
            timestamp=datetime.now(),
            provider_name="TestProvider",
            raw_response={"error": "test"},
            is_successful=False,
            error_message="Test error"
        )
        
        assert response.is_successful is False
        assert response.error_message == "Test error"
        assert response.rate == 0.0


class TestAPICallResult:
    """Test the APICallResult dataclass"""
    
    def test_successful_result_creation(self):
        """Test creating a successful API call result"""
        result = APICallResult(
            provider_name="TestProvider",
            endpoint="test",
            http_status_code=200,
            response_time_ms=150,
            was_successful=True,
            raw_response={"data": "test"}
        )
        
        assert result.provider_name == "TestProvider"
        assert result.endpoint == "test"
        assert result.http_status_code == 200
        assert result.response_time_ms == 150
        assert result.was_successful is True
        assert result.error_message is None
    
    def test_error_result_creation(self):
        """Test creating an error API call result"""
        result = APICallResult(
            provider_name="TestProvider",
            endpoint="test",
            http_status_code=404,
            response_time_ms=100,
            was_successful=False,
            error_message="Not found"
        )
        
        assert result.was_successful is False
        assert result.error_message == "Not found"
        assert result.data is None