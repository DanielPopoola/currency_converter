from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	DATABASE_URL: str = 'sqlite+aiosqlite:///./currency_converter.db'

	REDIS_URL: str = 'redis://localhost:6379'

	FIXERIO_API_KEY: str = ''
	OPENEXCHANGE_APP_ID: str = ''
	CURRENCYAPI_KEY: str = ''

	# Application
	APP_NAME: str = 'Currency Converter API'
	DEBUG: bool = True
	CORS_ORIGINS: str = (
		'http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173'
	)

	model_config = SettingsConfigDict(env_file='.env', case_sensitive=False, extra='ignore')


@lru_cache
def get_settings() -> Settings:
	return Settings()
