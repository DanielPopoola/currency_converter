import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime


from app.api.main import app
from app.api.dependencies import get_service_factory


@pytest.fixture
def mock_db_manager():
    mock_db = MagicMock()
    mock_db.health_check = AsyncMock(return_value={
        "status": "healthy",
        "response_time_ms": 12
    })
    return mock_db

@pytest.fixture
def mock_redis_manager():
    mock_redis = MagicMock()
    mock_redis.health_check = AsyncMock(return_value={
        "status": "healthy",
        "response_time_ms": 5
    })
    return mock_redis

@pytest.fixture
def mock_circuit_breaker():
    mock_cb = MagicMock()
    mock_cb.get_status = AsyncMock(return_value={
        "state": "CLOSED",
        "failure_count": 0,
        "success_count": 10,
        "last_failure_time": None
    })
    return mock_cb

@pytest.fixture
def mock_service_factory(mock_db_manager, mock_redis_manager, mock_circuit_breaker):
    mock_factory = MagicMock()

    mock_factory.get_db_manager = MagicMock(return_value=mock_db_manager)
    mock_factory.get_redis_manager = MagicMock(return_value=mock_redis_manager)
    mock_factory.rate_aggregator = MagicMock()
    mock_factory.rate_aggregator.primary_provider = "FixerIO"


    mock_factory.get_health_status = AsyncMock(return_value={
        "service": "healthy",
        "providers": {
            "FixerIO": {"status": "healthy"},
            "OpenExchange": {"status": "healthy"}
        }
    })
    
    mock_factory.circuit_breakers = {
        "FixerIO": mock_circuit_breaker,
        "OpenExchange": mock_circuit_breaker
    }
    
    return mock_factory

@pytest.fixture
def client(mock_service_factory):
    """Create test client with mocked service factory."""
    app.dependency_overrides[get_service_factory] = lambda: mock_service_factory
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_health_check_all_healthy(client, mock_service_factory):
    """Test health check when all services are healthy."""
    response = client.get("/api/v1/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check overall status
    assert data["status"] == "healthy"
    assert "timestamp" in data
    
    # Check individual services
    assert data["services"]["database"]["status"] == "healthy"
    assert data["services"]["cache"]["status"] == "healthy"
    assert data["services"]["rate_aggregator"]["service"] == "healthy"
    
    # Verify the mocks were called
    mock_service_factory.get_db_manager().health_check.assert_called_once()
    mock_service_factory.get_redis_manager().health_check.assert_called_once()
    mock_service_factory.get_health_status.assert_called_once()

def test_health_check_redis_unhealthy(mock_db_manager, mock_redis_manager, mock_circuit_breaker):
    """Test health check when Redis is down (non-critical service)."""
    # Make Redis unhealthy
    mock_redis_manager.health_check = AsyncMock(return_value={
        "status": "unhealthy",
        "error": "Connection failed"
    })
    
    # Build service factory with failing Redis
    mock_factory = MagicMock()
    mock_factory.get_db_manager = MagicMock(return_value=mock_db_manager)
    mock_factory.get_redis_manager = MagicMock(return_value=mock_redis_manager)
    mock_factory.rate_aggregator = MagicMock()
    mock_factory.get_health_status = AsyncMock(return_value={
        "service": "healthy"
    })
    
    # Create client
    app.dependency_overrides[get_service_factory] = lambda: mock_factory
    client = TestClient(app)
    
    response = client.get("/api/v1/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should be degraded (Redis is non-critical)
    assert data["status"] == "degraded"
    assert data["services"]["cache"]["status"] == "unhealthy"
    assert data["services"]["database"]["status"] == "healthy"
    
    app.dependency_overrides.clear()


# ============================================================================
# UNHEALTHY SCENARIOS (CRITICAL SERVICES DOWN)
# ============================================================================

def test_health_check_database_unhealthy(mock_db_manager, mock_redis_manager, mock_circuit_breaker):
    """Test health check when database is down (critical service)."""
    # Make database unhealthy
    mock_db_manager.health_check = AsyncMock(return_value={
        "status": "unhealthy",
        "error": "Connection failed"
    })
    
    # Build service factory
    mock_factory = MagicMock()
    mock_factory.get_db_manager = MagicMock(return_value=mock_db_manager)
    mock_factory.get_redis_manager = MagicMock(return_value=mock_redis_manager)
    mock_factory.rate_aggregator = MagicMock()
    mock_factory.get_health_status = AsyncMock(return_value={
        "service": "healthy"
    })
    
    app.dependency_overrides[get_service_factory] = lambda: mock_factory
    client = TestClient(app)
    
    response = client.get("/api/v1/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should be unhealthy (database is critical)
    assert data["status"] == "unhealthy"
    assert data["services"]["database"]["status"] == "unhealthy"
    
    app.dependency_overrides.clear()


def test_health_check_rate_aggregator_not_initialized(mock_db_manager, mock_redis_manager):
    """Test health check when rate aggregator hasn't been initialized yet."""
    # Build service factory without rate aggregator
    mock_factory = MagicMock()
    mock_factory.get_db_manager = MagicMock(return_value=mock_db_manager)
    mock_factory.get_redis_manager = MagicMock(return_value=mock_redis_manager)
    mock_factory.rate_aggregator = None  # Not initialized!
    
    app.dependency_overrides[get_service_factory] = lambda: mock_factory
    client = TestClient(app)
    
    response = client.get("/api/v1/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should be unhealthy (rate_aggregator is critical)
    assert data["status"] == "unhealthy"
    assert data["services"]["rate_aggregator"]["status"] == "not_initialized"
    
    app.dependency_overrides.clear()