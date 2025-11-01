import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from domain.exceptions.currency import InvalidCurrencyError, ProviderError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
	@app.exception_handler(InvalidCurrencyError)
	async def invalid_currency_handler(request: Request, exc: InvalidCurrencyError):
		return JSONResponse(status_code=400, content={'detail': str(exc)})

	@app.exception_handler(ProviderError)
	async def provider_error_handler(request: Request, exc: ProviderError):
		logger.error(f'Provider error: {exc}')
		return JSONResponse(
			status_code=503, content={'detail': 'Exchange rate service unavailable'}
		)
