from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC as a naive datetime for database portability."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(value: datetime) -> datetime:
    """Normalize an aware datetime to UTC and remove the offset before persistence."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_boot_time(value: datetime) -> datetime:
    """Normalize boot timestamps to UTC-naive whole-second precision.

    Windows may report sub-second boot timestamps while common MariaDB DATETIME
    columns persist only whole seconds. Treating those values as exact datetimes
    can therefore create false reboot detections across Agent batches.
    """
    return to_utc_naive(value).replace(microsecond=0)


def as_utc(value: datetime | None) -> datetime | None:
    """Expose a stored naive UTC datetime as an aware UTC datetime."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def duration_minutes(start: datetime, end: datetime) -> int:
    start_utc = to_utc_naive(start)
    end_utc = to_utc_naive(end)
    return max(0, int((end_utc - start_utc).total_seconds() // 60))
