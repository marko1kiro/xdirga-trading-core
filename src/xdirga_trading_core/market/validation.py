from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Sequence

from .models import Candle


class ReasonCode(str, Enum):
    EMPTY = "EMPTY"
    MIXED_SYMBOLS = "MIXED_SYMBOLS"
    MIXED_TIMEFRAMES = "MIXED_TIMEFRAMES"
    INVALID_ORDER = "INVALID_ORDER"
    DUPLICATE_TIMESTAMPS = "DUPLICATE_TIMESTAMPS"
    MISSING_TIMESTAMPS = "MISSING_TIMESTAMPS"
    STALE_LATEST = "STALE_LATEST"
    LATEST_UNCLOSED = "LATEST_UNCLOSED"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ordering_valid: bool
    duplicate_timestamps: tuple[datetime, ...]
    missing_timestamps: tuple[datetime, ...]
    latest_stale: bool
    latest_closed: bool
    trusted: bool
    reason_codes: tuple[ReasonCode, ...]


def validate_candles(
    candles: Sequence[Candle], *, now: datetime, max_age: timedelta
) -> ValidationResult:
    if now.tzinfo is not UTC:
        raise ValueError("now must be timezone-aware UTC")
    if max_age < timedelta():
        raise ValueError("max_age must not be negative")
    if not candles:
        return ValidationResult(False, (), (), False, False, False, (ReasonCode.EMPTY,))

    timestamps = tuple(candle.timestamp for candle in candles)
    seen: set[datetime] = set()
    duplicate_set: set[datetime] = set()
    duplicates: list[datetime] = []
    for timestamp in timestamps:
        if timestamp in seen and timestamp not in duplicate_set:
            duplicates.append(timestamp)
            duplicate_set.add(timestamp)
        seen.add(timestamp)
    ordering_valid = all(
        left < right for left, right in zip(timestamps, timestamps[1:], strict=False)
    )
    mixed_symbols = len({candle.symbol for candle in candles}) > 1
    mixed_timeframes = len({candle.timeframe for candle in candles}) > 1

    missing: list[datetime] = []
    if not mixed_timeframes and ordering_valid:
        duration = candles[0].timeframe.duration
        for left, right in zip(timestamps, timestamps[1:], strict=False):
            expected = left + duration
            while expected < right:
                missing.append(expected)
                expected += duration

    latest = candles[-1]
    stale = now - latest.timestamp > max_age
    reasons: list[ReasonCode] = []
    if mixed_symbols:
        reasons.append(ReasonCode.MIXED_SYMBOLS)
    if mixed_timeframes:
        reasons.append(ReasonCode.MIXED_TIMEFRAMES)
    if not ordering_valid:
        reasons.append(ReasonCode.INVALID_ORDER)
    if duplicates:
        reasons.append(ReasonCode.DUPLICATE_TIMESTAMPS)
    if missing:
        reasons.append(ReasonCode.MISSING_TIMESTAMPS)
    if stale:
        reasons.append(ReasonCode.STALE_LATEST)
    if not latest.closed:
        reasons.append(ReasonCode.LATEST_UNCLOSED)

    return ValidationResult(
        ordering_valid,
        tuple(duplicates),
        tuple(missing),
        stale,
        latest.closed,
        not reasons,
        tuple(reasons),
    )
