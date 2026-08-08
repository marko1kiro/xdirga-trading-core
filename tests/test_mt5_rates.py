from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from xdirga_trading_core.market import (
    Mt5RateNormalizationError,
    ReasonCode,
    Timeframe,
    normalize_mt5_rates,
    validate_candles,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class IntegralScalar:
    def __init__(self, value: int) -> None:
        self.value = value

    def __index__(self) -> int:
        return self.value


class ExplodingStr:
    def __str__(self) -> str:
        raise RuntimeError("str exploded")


class ExplodingIndex:
    def __index__(self) -> int:
        raise RuntimeError("index exploded")


class ExplodingRow(dict[str, object]):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def __getitem__(self, key: str) -> object:
        raise self.error


class FailingRows:
    def __init__(self, fail_after: int) -> None:
        self.fail_after = fail_after

    def __iter__(self):
        if self.fail_after == 0:
            raise RuntimeError("iteration exploded")
        yield row()
        raise RuntimeError("iteration exploded")


def row(time: object = 0, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "time": time,
        "open": 1.1,
        "high": "1.2",
        "low": Decimal("1.0"),
        "close": 1,
        "tick_volume": 10,
        "spread": 99,
        "real_volume": 999,
    }
    value.update(changes)
    return value


def normalize(
    rows: list[dict[str, object]],
    *,
    timeframe: Timeframe = Timeframe.M1,
    now: datetime = EPOCH,
):
    return normalize_mt5_rates(
        rows, symbol="EURUSD", timeframe=timeframe, now=now
    )


def test_empty_input_returns_empty_tuple() -> None:
    assert normalize([]) == ()


def test_valid_row_maps_all_fields() -> None:
    result = normalize(
        [row(IntegralScalar(60), tick_volume=IntegralScalar(7))], now=EPOCH
    )

    assert len(result) == 1
    candle = result[0]
    assert candle.symbol == "EURUSD"
    assert candle.timeframe is Timeframe.M1
    assert candle.timestamp == EPOCH + timedelta(minutes=1)
    assert (candle.open, candle.high, candle.low, candle.close) == (
        Decimal("1.1"),
        Decimal("1.2"),
        Decimal("1.0"),
        Decimal("1"),
    )
    assert candle.volume == Decimal("7")
    assert not candle.closed


def test_multiple_rows_preserve_input_order() -> None:
    result = normalize([row(120), row(60), row(60)])

    assert tuple(candle.timestamp for candle in result) == (
        EPOCH + timedelta(minutes=2),
        EPOCH + timedelta(minutes=1),
        EPOCH + timedelta(minutes=1),
    )


@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_each_timeframe_maps_aligned_timestamp(timeframe: Timeframe) -> None:
    seconds = int(timeframe.duration.total_seconds())

    candle = normalize([row(seconds)], timeframe=timeframe)[0]

    assert candle.timestamp == EPOCH + timeframe.duration
    assert candle.timeframe is timeframe


def test_epoch_conversion_is_utc_and_deterministic() -> None:
    first = normalize([row(1_767_225_600)], timeframe=Timeframe.M1)
    second = normalize([row(1_767_225_600)], timeframe=Timeframe.M1)

    assert first == second
    assert first[0].timestamp == datetime(2026, 1, 1, tzinfo=UTC)
    assert first[0].timestamp.tzinfo is UTC


@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_unaligned_timestamp_fails_for_each_timeframe(timeframe: Timeframe) -> None:
    with pytest.raises(
        Mt5RateNormalizationError, match=r"row\[0\]\.time: unaligned"
    ):
        normalize([row(1)], timeframe=timeframe)


@pytest.mark.parametrize(
    ("offset", "closed"),
    [(-1, False), (0, True), (1, True)],
)
def test_closed_boundary(offset: int, closed: bool) -> None:
    close_time = EPOCH + Timeframe.M1.duration

    candle = normalize([row(0)], now=close_time + timedelta(seconds=offset))[0]

    assert candle.closed is closed


def test_active_candle_is_preserved() -> None:
    result = normalize([row(60)], now=EPOCH)

    assert len(result) == 1
    assert not result[0].closed


def test_tick_volume_is_used_and_zero_is_valid() -> None:
    candle = normalize([row(tick_volume=0, real_volume=999)])[0]

    assert candle.volume == Decimal("0")


@pytest.mark.parametrize(
    "field", ["time", "open", "high", "low", "close", "tick_volume"]
)
def test_missing_field_identifies_row_and_field(field: str) -> None:
    value = row()
    del value[field]

    with pytest.raises(
        Mt5RateNormalizationError, match=rf"row\[0\]\.{field}: missing"
    ):
        normalize([value])


@pytest.mark.parametrize("symbol", ["", " ", " EURUSD", "EURUSD ", 1])
def test_malformed_symbol_fails_clearly(symbol: object) -> None:
    with pytest.raises(Mt5RateNormalizationError, match="argument symbol"):
        normalize_mt5_rates(
            [], symbol=symbol, timeframe=Timeframe.M1, now=EPOCH  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("timeframe", ["M1", 1, None])
def test_malformed_timeframe_fails_clearly(timeframe: object) -> None:
    with pytest.raises(Mt5RateNormalizationError, match="argument timeframe"):
        normalize_mt5_rates(
            [], symbol="EURUSD", timeframe=timeframe, now=EPOCH  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        "now",
    ],
)
def test_malformed_now_fails_clearly(now: object) -> None:
    with pytest.raises(Mt5RateNormalizationError, match="argument now"):
        normalize_mt5_rates(
            [], symbol="EURUSD", timeframe=Timeframe.M1, now=now  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "value", [-1, 1.5, "60", True, None, 10**100]
)
def test_malformed_timestamp_fails_clearly(value: object) -> None:
    with pytest.raises(Mt5RateNormalizationError, match=r"row\[0\]\.time"):
        normalize([row(value)])


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("value", [True, None, "bad", float("nan"), float("inf")])
def test_malformed_ohlc_fails_clearly(field: str, value: object) -> None:
    with pytest.raises(Mt5RateNormalizationError, match=rf"row\[0\]\.{field}"):
        normalize([row(**{field: value})])


def test_invalid_candle_geometry_fails_as_row_invariant() -> None:
    with pytest.raises(
        Mt5RateNormalizationError, match=r"row\[0\]\.invariant"
    ):
        normalize([row(high="0")])


@pytest.mark.parametrize("value", [-1, 1.5, "10", True, None])
def test_malformed_tick_volume_fails_clearly(value: object) -> None:
    with pytest.raises(Mt5RateNormalizationError, match=r"row\[0\]\.tick_volume"):
        normalize([row(tick_volume=value)])


def test_raising_str_is_wrapped_with_field_context() -> None:
    with pytest.raises(Mt5RateNormalizationError, match=r"row\[0\]\.open") as error:
        normalize([row(open=ExplodingStr())])

    assert isinstance(error.value.__cause__, RuntimeError)


@pytest.mark.parametrize("field", ["time", "tick_volume"])
def test_raising_index_is_wrapped_with_field_context(field: str) -> None:
    with pytest.raises(Mt5RateNormalizationError, match=rf"row\[0\]\.{field}") as error:
        normalize([row(**{field: ExplodingIndex()})])

    assert isinstance(error.value.__cause__, RuntimeError)


@pytest.mark.parametrize("cause", [IndexError("bad index"), RuntimeError("exploded")])
def test_abnormal_field_access_is_wrapped(cause: Exception) -> None:
    with pytest.raises(Mt5RateNormalizationError, match=r"row\[0\]\.time") as error:
        normalize([ExplodingRow(cause)])

    assert error.value.__cause__ is cause


def test_none_rows_is_wrapped_as_top_level_input_error() -> None:
    with pytest.raises(Mt5RateNormalizationError, match="rows: not iterable") as error:
        normalize_mt5_rates(
            None, symbol="EURUSD", timeframe=Timeframe.M1, now=EPOCH  # type: ignore[arg-type]
        )

    assert isinstance(error.value.__cause__, TypeError)


@pytest.mark.parametrize("fail_after", [0, 1])
def test_iterator_failure_has_deterministic_next_row_context(fail_after: int) -> None:
    with pytest.raises(
        Mt5RateNormalizationError, match=rf"row\[{fail_after}\]: iteration failed"
    ) as error:
        normalize_mt5_rates(
            FailingRows(fail_after),
            symbol="EURUSD",
            timeframe=Timeframe.M1,
            now=EPOCH,
        )

    assert isinstance(error.value.__cause__, RuntimeError)


def test_close_status_overflow_is_wrapped_as_row_invariant() -> None:
    max_delta = datetime.max.replace(tzinfo=UTC) - EPOCH
    max_seconds = max_delta.days * 86_400 + max_delta.seconds
    aligned_seconds = max_seconds // 60 * 60

    with pytest.raises(
        Mt5RateNormalizationError, match=r"row\[0\]\.invariant: close status"
    ) as error:
        normalize([row(aligned_seconds)], now=datetime.max.replace(tzinfo=UTC))

    assert isinstance(error.value.__cause__, OverflowError)


def test_batch_stops_at_first_bad_row_without_skipping() -> None:
    with pytest.raises(Mt5RateNormalizationError, match=r"row\[1\]\.open"):
        normalize([row(), row(open="bad"), row(120)])


def test_reversed_and_duplicate_rows_reach_sequence_validation() -> None:
    candles = normalize([row(120), row(60), row(60)], now=EPOCH + timedelta(minutes=3))
    result = validate_candles(
        candles,
        now=EPOCH + timedelta(minutes=3),
        max_age=timedelta(minutes=2),
    )

    assert result.reason_codes[:2] == (
        ReasonCode.INVALID_ORDER,
        ReasonCode.DUPLICATE_TIMESTAMPS,
    )


def test_closed_contiguous_batch_composes_as_trusted() -> None:
    now = EPOCH + timedelta(minutes=3)
    candles = normalize([row(60), row(120)], now=now)

    result = validate_candles(candles, now=now, max_age=timedelta(minutes=1))

    assert result.trusted


def test_active_latest_candle_composes_as_untrusted() -> None:
    now = EPOCH + timedelta(seconds=90)
    candles = normalize([row(0), row(60)], now=now)

    result = validate_candles(candles, now=now, max_age=timedelta(minutes=1))

    assert not result.trusted
    assert ReasonCode.LATEST_UNCLOSED in result.reason_codes
