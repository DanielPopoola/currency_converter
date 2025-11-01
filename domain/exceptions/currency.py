class CurrencyException(Exception):
    pass


class InvalidCurrencyError(CurrencyException):
    pass

class ProviderError(CurrencyException):
    pass

class CacheError(CurrencyException):
    pass