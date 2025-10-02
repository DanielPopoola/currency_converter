import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import ValidationException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import convert, health, rates, websockets
from app.config.database import DatabaseManager
from app.monitoring.logger import logger
from app.services.service_factory import service_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize logger
    logger.info("Starting Currency Converter API...")

    try:
        logger.info("Setting up database...")
        #service_factory.db_manager.create_tables()
        service_factory.db_manager.seed_initial_data()

        # Initialize services  
        logger.info("Initializing services...")
        await service_factory.create_rate_aggregator()
        
        # Test connections
        logger.info("Testing service connections...")
        
        # Test Redis
        redis_health = await service_factory.get_redis_manager().health_check()
        if redis_health["status"] == "healthy":
            logger.info("✅ Redis connection established")
        else:
            logger.warning("⚠️  Redis connection issues detected")

        # Test Database
        db_health = await service_factory.get_db_manager().health_check()
        if db_health["status"] == "healthy":
            logger.info("✅ Database connection established")
        else:
            logger.warning("⚠️  Database connection issues detected")
        
        # Test rate aggregator
        aggregator_health = await service_factory.get_health_status()
        logger.info(f"Rate aggregator status: {aggregator_health.get('service', 'unknown')}")
        
        logger.info("🚀 Currency Converter API started successfully!")
        
    except Exception as e:
        logger.error(f"Failed to start services: {e}")
        raise
    
    yield

    logger.info("Shutting down Currency Converter API...")
    try:
        await service_factory.cleanup()
        logger.info("✅ Services cleaned up successfully")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

app = FastAPI(
    title="Currency Converter API",
    description="A robust currency conversion service with multiple API providers, circuit breakers, and caching",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with consistent format"""
    logger.error(
        "HTTPException caught: Status {status_code}, Detail: {detail}",
        status_code=exc.status_code,
        detail=exc.detail,
        timestamp=datetime.now()
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "http_error",
            "message": exc.detail,
            "timestamp": datetime.now().isoformat(),
            "path": str(request.url.path)
        }
    )


@app.exception_handler(ValidationException)
async def validation_exception_handler(request: Request, exc: ValidationException):
    """Handle Pydantic validation errors"""
    logger.warning(
        "Validation error on {path}: {error}",
        path=request.url.path,
        error=str(exc),
        timestamp=datetime.now()
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "Invalid request data",
            "details": exc.errors(),
            "timestamp": datetime.now().isoformat(),
            "path": str(request.url.path)
        }
    )


app.include_router(convert.router)
app.include_router(rates.router)
app.include_router(health.router)
app.include_router(websockets.router)

@app.get(
    "/",
    summary="API Information",
    description="Get basic information about the Currency Converter API"
)
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Currency Converter API",
        "version": "1.0.0",
        "description": "A robust currency conversion service",
        "endpoints": {
            "conversion": "/api/v1/convert",
            "rates": "/api/v1/rates", 
            "health": "/api/v1/health",
            "documentation": "/docs"
        },
        "features": [
            "Multiple API provider support",
            "Circuit breaker pattern",
            "Redis caching (5-minute TTL)",
            "Graceful fallback handling",
            "Comprehensive health monitoring"
        ],
        "timestamp": datetime.now().isoformat()
    }

"""
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()

    # Process request
    response = await call_next(request)
        
    # Calculate response time
    response_time = (datetime.now() - start_time).total_seconds() * 1000
    
    # Log response
    status_emoji = "✅" if response.status_code < 400 else "❌"
    logger.info(f"⬅️  {status_emoji} {response.status_code} {request.method} {request.url.path} ({response_time:.2f}ms)")
    
    return response
"""

if __name__ == "__main__":
    import uvicorn
    
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    
    logger.info(f"Starting server on {host}:{port}")
    
    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        reload=os.getenv("ENVIRONMENT", "production") == "development",
        log_level="info"
    )