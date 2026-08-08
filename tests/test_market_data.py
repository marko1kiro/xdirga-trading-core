from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from xdirga_trading_core.market import (
    Candle,
    ReasonCode,
    Timeframe,
    validate_candles,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def candle(
    minute: int = 0,
    *,
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.M1,
    closed: bool = True,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=BASE + timedelta(minutes=minute),
        open=Decimal("1.10"),
        high=Decimal("1.20"),
        low=Decimal("1.00"),
        close=Decimal("1.15"),
        volume=Decimal("10"),
        closed=closed,
    )


def test_valid_candle_is_immutable() -> None:
    value = candle()

    assert value.symbol == "EURUSD"
    with pytest.raises(FrozenInstanceError):
        value.close = Decimal("2")  # type: ignore[misc]


@pytest.mark.parametrize("symbol", ["", "   "])
def test_candle_rejects_empty_symbol(symbol: str) -> None:
    with pytest.raises(ValueError, match="symbol must not be empty"):
        candle(symbol=symbol)


@pytest.mark.parametrize(
    ("timestamp", "message"),
    [
        (datetime(2026, 1, 1), "timestamp must be timezone-aware UTC"),
        (
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            "timestamp must be timezone-aware UTC",
        ),
    ],
)
def test_candle_rejects_non_utc_timestamp(
    timestamp: datetime, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Candle(
            "EURUSD",
            Timeframe.M1,
            timestamp,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            True,
        )


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_candle_rejects_non_finite_numbers(field: str, value: Decimal) -> None:
    values = {
        "symbol": "EURUSD",
        "timeframe": Timeframe.M1,
        "timestamp": BASE,
        "open": Decimal("1.10"),
        "high": Decimal("1.20"),
        "low": Decimal("1.00"),
        "close": Decimal("1.15"),
        "volume": Decimal("10"),
        "closed": True,
    }
    values[field] = value

    with pytest.raises(ValueError, match=f"{field} must be finite"):
        Candle(**values)  # type: ignore[arg-type]


def test_candle_rejects_negative_volume() -> None:
    with pytest.raises(ValueError, match="volume must not be negative"):
        Candle(
            "EURUSD",
            Timeframe.M1,
            BASE,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("-1"),
            True,
        )


@pytest.mark.parametrize(
    ("open_", "high", "low", "close", "message"),
    [
        ("2", "1", "0", "1", "high must not be below OHLC values"),
        ("1", "1", "0", "2", "high must not be below OHLC values"),
        ("0", "2", "1", "2", "low must not be above OHLC values"),
    ],
)
def test_candle_rejects_invalid_ohlc_bounds(
    open_: str, high: str, low: str, close: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Candle(
            "EURUSD",
            Timeframe.M1,
            BASE,
            Decimal(open_),
            Decimal(high),
            Decimal(low),
            Decimal(close),
            Decimal("1"),
            True,
        )


@pytest.mark.parametrize("timeframe", ["M1", "M2", 1, None])
def test_candle_rejects_non_timeframe_values(timeframe: object) -> None:
    with pytest.raises(ValueError, match="timeframe must be a Timeframe"):
        Candle(
            "EURUSD",
            timeframe,  # type: ignore[arg-type]
            BASE,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            True,
        )


@pytest.mark.parametrize("closed", ["true", "", 0, 1, None])
def test_candle_rejects_non_bool_closed_values(closed: object) -> None:
    with pytest.raises(ValueError, match="closed must be a bool"):
        Candle(
            "EURUSD",
            Timeframe.M1,
            BASE,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            closed,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [1, 1.0, float("nan"), float("inf"), "1", None])
def test_candle_rejects_non_decimal_numbers(field: str, value: object) -> None:
    values = {
        "symbol": "EURUSD",
        "timeframe": Timeframe.M1,
        "timestamp": BASE,
        "open": Decimal("1.10"),
        "high": Decimal("1.20"),
        "low": Decimal("1.00"),
        "close": Decimal("1.15"),
        "volume": Decimal("10"),
        "closed": True,
    }
    values[field] = value

    with pytest.raises(ValueError, match=f"{field} must be a Decimal"):
        Candle(**values)  # type: ignore[arg-type]


def test_malformed_candle_cannot_enter_trusted_validation() -> None:
    with pytest.raises(ValueError, match="closed must be a bool"):
        malformed = Candle(
            "EURUSD",
            Timeframe.M1,
            BASE,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            "true",  # type: ignore[arg-type]
        )
        validate_candles([malformed], now=BASE, max_age=timedelta())


def test_timeframe_durations_are_exact() -> None:
    assert {timeframe: timeframe.duration for timeframe in Timeframe} == {
        Timeframe.M1: timedelta(minutes=1),
        Timeframe.M5: timedelta(minutes=5),
        Timeframe.M15: timedelta(minutes=15),
        Timeframe.H1: timedelta(hours=1),
    }


def test_trusted_sequence() -> None:
    result = validate_candles(
        [candle(0), candle(1), candle(2)],
        now=BASE + timedelta(minutes=3),
        max_age=timedelta(minutes=1),
    )

    assert result.trusted
    assert result.ordering_valid
    assert result.duplicate_timestamps == ()
    assert result.missing_timestamps == ()
    assert not result.latest_stale
    assert result.latest_closed
    assert result.reason_codes == ()


def test_empty_sequence_is_untrusted() -> None:
    result = validate_candles([], now=BASE, max_age=timedelta())

    assert not result.trusted
    assert result.reason_codes == (ReasonCode.EMPTY,)


def test_mixed_symbols_are_untrusted() -> None:
    result = validate_candles(
        [candle(), candle(1, symbol="GBPUSD")],
        now=BASE + timedelta(minutes=1),
        max_age=timedelta(),
    )

    assert result.reason_codes == (ReasonCode.MIXED_SYMBOLS,)


def test_mixed_timeframes_are_untrusted() -> None:
    result = validate_candles(
        [candle(), candle(5, timeframe=Timeframe.M5)],
        now=BASE + timedelta(minutes=5),
        max_age=timedelta(),
    )

    assert result.reason_codes == (ReasonCode.MIXED_TIMEFRAMES,)


def test_out_of_order_sequence_is_untrusted() -> None:
    result = validate_candles(
        [candle(1), candle(0)],
        now=BASE,
        max_age=timedelta(),
    )

    assert not result.ordering_valid
    assert result.reason_codes == (ReasonCode.INVALID_ORDER,)


def test_duplicate_timestamps_are_identified_once() -> None:
    result = validate_candles(
        [candle(), candle(), candle()], now=BASE, max_age=timedelta()
    )

    assert result.duplicate_timestamps == (BASE,)
    assert result.reason_codes == (
        ReasonCode.INVALID_ORDER,
        ReasonCode.DUPLICATE_TIMESTAMPS,
    )


@pytest.mark.parametrize(
    ("minutes", "missing"),
    [
        ([0, 2], [1]),
        ([0, 3], [1, 2]),
    ],
)
def test_missing_timestamps_are_identified(
    minutes: list[int], missing: list[int]
) -> None:
    result = validate_candles(
        [candle(minute) for minute in minutes],
        now=BASE + timedelta(minutes=minutes[-1]),
        max_age=timedelta(),
    )

    assert result.missing_timestamps == tuple(
        BASE + timedelta(minutes=minute) for minute in missing
    )
    assert result.reason_codes == (ReasonCode.MISSING_TIMESTAMPS,)


def test_latest_candle_older_than_max_age_is_stale() -> None:
    result = validate_candles(
        [candle()], now=BASE + timedelta(seconds=61), max_age=timedelta(minutes=1)
    )

    assert result.latest_stale
    assert result.reason_codes == (ReasonCode.STALE_LATEST,)


def test_latest_candle_at_max_age_is_fresh() -> None:
    result = validate_candles(
        [candle()], now=BASE + timedelta(minutes=1), max_age=timedelta(minutes=1)
    )

    assert result.trusted
    assert not result.latest_stale


def test_unclosed_latest_candle_is_untrusted() -> None:
    result = validate_candles(
        [candle(closed=False)], now=BASE, max_age=timedelta()
    )

    assert not result.latest_closed
    assert result.reason_codes == (ReasonCode.LATEST_UNCLOSED,)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_validation_rejects_non_utc_now(now: datetime) -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware UTC"):
        validate_candles([candle()], now=now, max_age=timedelta())


def test_validation_rejects_negative_max_age() -> None:
    with pytest.raises(ValueError, match="max_age must not be negative"):
        validate_candles([candle()], now=BASE, max_age=timedelta(seconds=-1))


def test_validation_is_deterministic() -> None:
    candles = [candle(0), candle(2), candle(2, closed=False)]
    arguments = {"now": BASE + timedelta(minutes=4), "max_age": timedelta(minutes=1)}

    assert validate_candles(candles, **arguments) == validate_candles(
        candles, **arguments
    )
