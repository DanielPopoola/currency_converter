from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	DATABASE_URL: str = 'sqlite+aiosqlite:///./currency_converter.db'

	REDIS_URL: str = 'redis://localhost:6379'

	FIXERIO_API_KEY: str = ''
	OPENEXCHANGE_APP_ID: str = ''
	CURRENCYAPI_API_KEY: str = ''

	# Application
	APP_NAME: str = 'Currency Converter API'
	DEBUG: bool = True

	model_config = SettingsConfigDict(env_file='.env', case_sensitive=False, extra='ignore')


@lru_cache
def get_settings() -> Settings:
	return Settings()
