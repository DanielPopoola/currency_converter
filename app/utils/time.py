from datetime import datetime, timedelta

def get_adjusted_timestamp() -> datetime:
    """Returns the current UTC time plus one hour."""
    return datetime.utcnow() + timedelta(hours=1)

def adjust_timestamp(dt: datetime) -> datetime:
    """Adds one hour to a given datetime object."""
    return dt + timedelta(hours=1)
