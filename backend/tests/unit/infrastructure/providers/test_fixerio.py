# nosec B101


import pytest
from decimal import Decimal
from unittest.mock import Mock, AsyncMock
import httpx

from infrastructure.providers.fixerio import FixerIOProvider
from domain.exceptions.currency import ProviderError


@pytest.mark.asyncio
async def test_fetch_rate_success_returns_decimal():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': True,
        'base': 'USD',
        'rates': {'EUR': 0.85}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)

    rate = await provider.fetch_rate('USD', 'EUR')

    assert rate == Decimal('0.85')
    assert isinstance(rate, Decimal)
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert 'http://data.fixer.io/api/latest' in call_args[0][0]
    assert call_args[1]['params']['access_key'] == 'test_key'
    assert call_args[1]['params']['base'] == 'USD'
    assert call_args[1]['params']['symbols'] == 'EUR'


@pytest.mark.asyncio
async def test_fetch_rate_different_currencies():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': True,
        'rates': {'JPY': 110.50}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)

    rate = await provider.fetch_rate('USD', 'JPY')

    assert rate == Decimal('110.50')

@pytest.mark.asyncio
async def test_fetch_rate_api_returns_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': False,
        'error': {
            'code': 101,
            'info': 'Invalid API key'
        }
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key="invalid_key", client=mock_client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert 'Invalid API key' in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_rate_missing_rate_in_response():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': True,
        'rates': {}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert 'Missing rate for EUR' in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_rate_http_500_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    error_response = Mock()
    error_response.status_code = 500
    error_response.text = 'Internal Server Error'

    mock_client.get.side_effect = httpx.HTTPStatusError(
        'Server error',
        request=Mock(),
        response=error_response
    )

    provider = FixerIOProvider(api_key='test_key', client=mock_client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert 'HTTP error 500' in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_rate_http_429_rate_limit():
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    error_response = Mock()
    error_response.status_code = 429
    error_response.text = 'Rate limit exceeded'

    mock_client.get.side_effect = httpx.HTTPStatusError(
        'Rate limit',
        request=Mock(),
        response=error_response
    )
    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert '429' in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_rate_network_timeout():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.TimeoutException('Request timed out')
    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert 'request failed' in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_fetch_rate_connection_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.ConnectError('Connection refused')
    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert 'request failed' in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_fetch_rate_invalid_json_response():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.raise_for_status = Mock()

    mock_response.json.side_effect = ValueError('Invalid JSON')
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    with pytest.raises(ProviderError) as exc_info:
        await provider.fetch_rate('USD', 'EUR')

    assert 'parsing error' in str(exc_info.value).lower()


# ============================================================================
# TEST: fetch_supported_currencies() - Success Scenarios
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_supported_currencies_success():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': True,
        'symbols': {
            'USD': 'United States Dollar',
            'EUR': 'Euro',
            'GBP': 'British Pound Sterling'
        }
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    currencies = await provider.fetch_supported_currencies()

    assert len(currencies) == 3
    assert all(isinstance(c, dict) for c in currencies)
    assert all('code' in c and 'name' in c for c in currencies)

    usd = next(c for c in currencies if c['code'] == 'USD')
    assert usd['name'] == 'United States Dollar'


@pytest.mark.asyncio
async def test_fetch_supported_currencies_api_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': False,
        'error': {'info': 'Endpoint not available'}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    with pytest.raises(ProviderError):
        await provider.fetch_supported_currencies()



# ============================================================================
# TEST: Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_rate_with_very_small_rate():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': True,
        'rates': {'XXX': 0.00001234}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    rate = await provider.fetch_rate('USD', 'XXX')

    assert rate == Decimal('0.00001234')
    assert str(rate) == '0.00001234'


@pytest.mark.asyncio
async def test_fetch_rate_with_very_large_rate():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        'success': True,
        'rates': {'ZZZ': 1234567.89}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key='test_key', client=mock_client)
    rate = await provider.fetch_rate('USD', 'ZZZ')

    assert rate == Decimal('1234567.89')
