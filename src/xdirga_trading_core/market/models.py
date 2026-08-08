from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum


class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"

    @property
    def duration(self) -> timedelta:
        return {
            Timeframe.M1: timedelta(minutes=1),
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.H1: timedelta(hours=1),
        }[self]


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    closed: bool

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not isinstance(self.timeframe, Timeframe):
            raise ValueError("timeframe must be a Timeframe")
        if self.timestamp.tzinfo is not UTC:
            raise ValueError("timestamp must be timezone-aware UTC")
        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise ValueError(f"{name} must be a Decimal")
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
        if not isinstance(self.closed, bool):
            raise ValueError("closed must be a bool")
        if self.volume < 0:
            raise ValueError("volume must not be negative")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must not be below OHLC values")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must not be above OHLC values")
