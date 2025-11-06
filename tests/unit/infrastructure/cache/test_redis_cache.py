# nosec B101


import pytest
import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, call


from infrastructure.cache.redis_cache import RedisCacheService
from domain.models.currency import ExchangeRate
from domain.exceptions.currency import CacheError


@pytest.mark.asyncio
async def test_get_rate_cache_hit_returns_exchange_rate():
    mock_redis = AsyncMock()
    cached_data = json.dumps({
        'from_currency': 'USD',
        'to_currency': 'EUR',
        'rate': '0.85',
        'timestamp': '2025-11-05T10:30:00',
        'source': 'fixerio'
    })

    mock_redis.get.return_value = cached_data
    cache_service = RedisCacheService(redis_client=mock_redis)
    result = await cache_service.get_rate('USD', 'EUR')

    assert result is not None
    assert isinstance(result, ExchangeRate)
    assert result.from_currency == 'USD'
    assert result.to_currency == 'EUR'
    assert result.rate == Decimal('0.85')
    assert isinstance(result.rate, Decimal)
    assert result.timestamp == datetime(2025, 11, 5, 10, 30, 0)
    assert result.source == 'fixerio'

    mock_redis.get.assert_called_once_with('rate:USD:EUR')

@pytest.mark.asyncio
async def test_get_rate_cache_miss_returns_none():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    cache_service = RedisCacheService(redis_client=mock_redis)

    result = await cache_service.get_rate('USD', 'EUR')
    assert result is None
    mock_redis.get.assert_called_once_with('rate:USD:EUR')

@pytest.mark.asyncio
async def test_get_rate_different_currency_pairs_use_diff_keys():
    mock_redis = AsyncMock()

    def redis_get_side_effect(key):
        if key == 'rate:USD:EUR':
            return json.dumps({
                'from_currency': 'USD', 'to_currency': 'EUR',
                'rate': '0.85', 'timestamp': '2025-11-05T10:00:00', 'source': 'test'
            })
        elif key == 'rate:EUR:GBP':
            return json.dumps({
                'from_currency': 'EUR', 'to_currency': 'GBP',
                'rate': '0.90', 'timestamp': '2025-11-05T10:00:00', 'source': 'test'
            })
        return None
    mock_redis.get.side_effect = redis_get_side_effect

    cache_service = RedisCacheService(redis_client=mock_redis)

    result1 = await cache_service.get_rate('USD', 'EUR')
    assert result1.rate == Decimal('0.85')

    result2 = await cache_service.get_rate('EUR', 'GBP')
    assert result2.rate == Decimal('0.90')

    assert mock_redis.get.call_count == 2
    mock_redis.get.assert_any_call('rate:USD:EUR')
    mock_redis.get.assert_any_call('rate:EUR:GBP')

# ============================================================================
# TEST: get_rate() - Edge Cases and Error Scenarios
# ============================================================================

@pytest.mark.asyncio
async def test_get_rate_malformed_json_returns_none():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "{ invalid json }"

    cache_service = RedisCacheService(redis_client=mock_redis)

    with pytest.raises(CacheError) as exc_info:
        result = await cache_service.get_rate('USD', 'EUR')

    assert 'Invalid json data' in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_rate_preserves_decimal_precision():
    mock_redis = AsyncMock()

    cached_data = json.dumps({
        'from_currency': 'BTC', 'to_currency': 'USD',
        'rate': '43521.123456',
        'timestamp': '2025-11-05T10:00:00', 'source': 'test'
    })
    mock_redis.get.return_value = cached_data

    cache_service = RedisCacheService(redis_client=mock_redis)
    result = await cache_service.get_rate('BTC', 'USD')

    assert result.rate == Decimal('43521.123456')
    assert str(result.rate) == '43521.123456'


# ============================================================================
# TEST: set_rate() - Cache Write Scenarios
# ============================================================================

@pytest.mark.asyncio
async def test_set_rate_serializes_and_stores_with_ttl():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    # Create rate to cache
    rate = ExchangeRate(
        from_currency='USD',
        to_currency='EUR',
        rate=Decimal('0.85'),
        timestamp=datetime(2025, 11, 5, 10, 30, 0),
        source='fixerio'
    )

    await cache_service.set_rate(rate)

    mock_redis.setex.assert_called_once()

    call_args = mock_redis.setex.call_args
    key = call_args[0][0]
    ttl = call_args[0][1]
    stored_data = call_args[0][2]

    assert key == 'rate:USD:EUR'
    assert ttl == timedelta(minutes=5)

    stored_dict = json.loads(stored_data)
    assert stored_dict['from_currency'] == 'USD'
    assert stored_dict['to_currency'] == 'EUR'
    assert stored_dict['rate'] == '0.85'
    assert stored_dict['timestamp'] == '2025-11-05T10:30:00'
    assert stored_dict['source'] == 'fixerio'


@pytest.mark.asyncio
async def test_set_rate_handles_high_precision_decimals():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    rate = ExchangeRate(
        from_currency='USD', to_currency='JPY',
        rate=Decimal('110.123456789'),
        timestamp=datetime.now(), source='test'
    )

    await cache_service.set_rate(rate)

    call_args = mock_redis.setex.call_args
    stored_data = call_args[0][2]
    stored_dict = json.loads(stored_data)

    assert stored_dict['rate'] == '110.123456789'


@pytest.mark.asyncio
async def test_set_rate_round_trip_consistency():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    # Original rate
    original_rate = ExchangeRate(
        from_currency='GBP', to_currency='USD',
        rate=Decimal('1.25'),
        timestamp=datetime(2025, 11, 5, 15, 45, 30),
        source='averaged'
    )

    await cache_service.set_rate(original_rate)

    stored_json = mock_redis.setex.call_args[0][2]
    mock_redis.get.return_value = stored_json
    retrieved_rate = await cache_service.get_rate('GBP', 'USD')

    assert retrieved_rate.from_currency == original_rate.from_currency
    assert retrieved_rate.to_currency == original_rate.to_currency
    assert retrieved_rate.rate == original_rate.rate
    assert retrieved_rate.timestamp == original_rate.timestamp
    assert retrieved_rate.source == original_rate.source


# ============================================================================
# TEST: Supported Currencies Caching
# ============================================================================

@pytest.mark.asyncio
async def test_get_supported_currencies_cache_hit():
    mock_redis = AsyncMock()

    cached_data = json.dumps(['USD', 'EUR', 'GBP', 'JPY'])
    mock_redis.get.return_value = cached_data

    cache_service = RedisCacheService(redis_client=mock_redis)

    result = await cache_service.get_supported_currencies()

    assert result == ['USD', 'EUR', 'GBP', 'JPY']
    assert isinstance(result, list)
    mock_redis.get.assert_called_once_with('currencies:supported')


@pytest.mark.asyncio
async def test_get_supported_currencies_cache_miss():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    cache_service = RedisCacheService(redis_client=mock_redis)

    result = await cache_service.get_supported_currencies()

    assert result is None


@pytest.mark.asyncio
async def test_set_supported_currencies_stores_with_ttl():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD']

    await cache_service.set_supported_currencies(currencies)

    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args

    assert call_args[0][0] == 'currencies:supported'
    assert call_args[0][1] == timedelta(hours=24)

    stored_data = json.loads(call_args[0][2])
    assert stored_data == currencies


@pytest.mark.asyncio
async def test_supported_currencies_round_trip():

    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    original_currencies = ['USD', 'EUR', 'GBP']

    await cache_service.set_supported_currencies(original_currencies)
    stored_json = mock_redis.setex.call_args[0][2]

    mock_redis.get.return_value = stored_json
    retrieved = await cache_service.get_supported_currencies()

    assert retrieved == original_currencies


# ============================================================================
# TEST: Key Generation Logic
# ============================================================================

def test_make_rate_key_format():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    key = cache_service._make_rate_key('USD', 'EUR')

    assert key == 'rate:USD:EUR'
    assert key.startswith('rate:')
    assert 'USD' in key
    assert 'EUR' in key


def test_make_rate_key_different_pairs_different_keys():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    key1 = cache_service._make_rate_key('USD', 'EUR')
    key2 = cache_service._make_rate_key('EUR', 'USD')
    key3 = cache_service._make_rate_key('GBP', 'JPY')

    assert key1 != key2
    assert key1 != key3
    assert key2 != key3

    # But consistent for same pair
    assert cache_service._make_rate_key('USD', 'EUR') == key1


# ============================================================================
# TEST: TTL Configuration
# ============================================================================

def test_default_ttl_values():
    mock_redis = AsyncMock()
    cache_service = RedisCacheService(redis_client=mock_redis)

    assert cache_service.rate_ttl == timedelta(minutes=5)
    assert cache_service.currency_ttl == timedelta(hours=24)
