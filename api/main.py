import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.dependencies import bootstrap, cleanup_dependencies, init_dependencies
from api.error_handlers import register_exception_handlers
from api.routes import currency
from config.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
	logger.info('Starting Currency Converter API...')

	init_dependencies()
	await bootstrap()

	logger.info('Application ready')

	yield

	logger.info('Shutting down...')
	await cleanup_dependencies()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
	logger.error(f'Unhandled exception: {exc}', exc_info=True)
	return JSONResponse(status_code=500, content={'detail': 'Internal server error'})


app.include_router(currency.router)
register_exception_handlers(app)
