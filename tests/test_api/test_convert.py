from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_rate_aggregator
from app.api.main import app


@pytest.fixture
def mock_rate_aggregator():
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.rate = Decimal("0.85")
    mock_result.confidence_level = "high"
    mock_result.timestamp = datetime(2025, 9, 30, 10, 0, 0)

    mock_service.get_exchange_rate = AsyncMock(return_value=mock_result)

    return mock_service


@pytest.fixture
def client(mock_rate_aggregator):
    # Override the real dependency with mock
    app.dependency_overrides[get_rate_aggregator] = lambda: mock_rate_aggregator
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_convert_currency_success(client, mock_rate_aggregator):
    # Prepare request
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": 100.00
    }

    response = client.post("/api/v1/convert", json=request_data)

    assert response.status_code == 200
    data = response.json()

    assert data["from_currency"] == "USD"
    assert data["to_currency"] == "EUR"
    assert Decimal(data["amount"]) == Decimal("100.00")
    assert Decimal(data["converted_amount"]) == Decimal("85.00")
    assert Decimal(data["exchange_rate"]) == Decimal("0.85")
    assert data["confidence_level"] == "high"
    assert "timestamp" in data

    mock_rate_aggregator.get_exchange_rate.assert_called_once_with("USD", "EUR")

def test_currency_convert_with_decimal_amount(client, mock_rate_aggregator):
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": 50.75
    }

    response = client.post("/api/v1/convert", json=request_data)

    assert response.status_code == 200
    data = response.json()

    assert Decimal(data["amount"]) == Decimal("50.75")
    # 50.75 * 0.85 = 43.1375, rounded to 43.14
    assert Decimal(data["converted_amount"]) == Decimal("43.14")


def test_convert_lowercase_currencies_normalized(client, mock_rate_aggregator):
    """Test that lowercase currency codes are normalized to uppercase."""
    request_data = {
        "from_currency": "usd",  # lowercase
        "to_currency": "eur",    # lowercase
        "amount": 100
    }
    
    response = client.post("/api/v1/convert", json=request_data)
    
    assert response.status_code == 200
    data = response.json()
    
    # Should be normalized to uppercase
    assert data["from_currency"] == "USD"
    assert data["to_currency"] == "EUR"
    
    # Service should be called with uppercase
    mock_rate_aggregator.get_exchange_rate.assert_called_once_with("USD", "EUR")

def test_convert_negative_amount(client):
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": -100
    }
    response = client.post("/api/v1/convert", json=request_data)
    assert response.status_code == 422

def test_convert_zero_amount(client):
    """Test that zero amount is rejected."""
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": 0
    }
    response = client.post("/api/v1/convert", json=request_data)    
    assert response.status_code == 422

def test_convert_same_currency(client):
    """Test that converting from same currency to same currency is rejected."""
    request_data = {
        "from_currency": "USD",
        "to_currency": "USD",
        "amount": 100
    }
    response = client.post("/api/v1/convert", json=request_data)
    assert response.status_code == 422

def test_convert_invalid_currency_code_too_short(client):
    """Test that currency codes shorter than 3 characters are rejected."""
    request_data = {
        "from_currency": "US",  # Too short
        "to_currency": "EUR",
        "amount": 100
    }
    response = client.post("/api/v1/convert", json=request_data)
    assert response.status_code == 422

def test_convert_invalid_currency_code_too_long(client):
    """Test that currency codes longer than 5 characters are rejected."""
    request_data = {
        "from_currency": "USDDDD",  # Too long
        "to_currency": "EUR",
        "amount": 100
    }
    response = client.post("/api/v1/convert", json=request_data)
    assert response.status_code == 422


def test_convert_missing_required_fields(client):
    """Test that missing required fields are rejected."""
    # Missing amount
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR"
    }
    response = client.post("/api/v1/convert", json=request_data)
    assert response.status_code == 422

def test_convert_invalid_amount_type(client):
    """Test that non-numeric amounts are rejected."""
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": "not_a_number"
    }
    response = client.post("/api/v1/convert", json=request_data)
    assert response.status_code == 422


# Service Error Cases

def test_convert_currency_validation_error(mock_rate_aggregator):
    """Test handling of currency validation errors from the service."""
    mock_rate_aggregator.get_exchange_rate = AsyncMock(
        side_effect=ValueError("Invalid currency code: XYZ")
    )

    app.dependency_overrides[get_rate_aggregator] = lambda: mock_rate_aggregator
    client = TestClient(app)

    request_data = {
        "from_currency": "USD",
        "to_currency": "XYZ",  # Invalid currency
        "amount": 100
    }
    
    response = client.post("/api/v1/convert", json=request_data)
    
    # Should return 400 for currency validation error
    assert response.status_code == 400
    data = response.json()
    assert "Currency validation failed" in data["message"]
    
    app.dependency_overrides.clear()


def test_convert_service_unavailable(mock_rate_aggregator):
    """Test handling when the rate service is completely unavailable."""
    mock_rate_aggregator.get_exchange_rate = AsyncMock(
        side_effect=Exception("Service connection failed")
    )
    
    app.dependency_overrides[get_rate_aggregator] = lambda: mock_rate_aggregator
    client = TestClient(app)
    
    request_data = {
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": 100
    }
    
    response = client.post("/api/v1/convert", json=request_data)
    
    # Should return 503 for service unavailable
    assert response.status_code == 503
    data = response.json()
    assert "Service temporarily unavailable" in data["message"]
    
    app.dependency_overrides.clear()