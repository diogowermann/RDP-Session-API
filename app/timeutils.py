from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC as a naive datetime for database portability."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(value: datetime) -> datetime:
    """Normalize an aware datetime to UTC and remove the offset before persistence."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def duration_minutes(start: datetime, end: datetime) -> int:
    start_utc = to_utc_naive(start)
    end_utc = to_utc_naive(end)
    return max(0, int((end_utc - start_utc).total_seconds() // 60))
