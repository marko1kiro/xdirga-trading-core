from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from operator import index

from .models import Candle, Timeframe


class Mt5RateNormalizationError(ValueError):
    pass


def _argument_error(name: str, detail: str) -> Mt5RateNormalizationError:
    return Mt5RateNormalizationError(f"argument {name}: {detail}")


def _row_value(row: Mapping[str, object], row_index: int, field: str) -> object:
    try:
        return row[field]
    except Exception as exc:
        detail = "missing" if isinstance(exc, KeyError) else "access failed"
        raise Mt5RateNormalizationError(
            f"row[{row_index}].{field}: {detail}"
        ) from exc


def _whole_number(raw: object, row_index: int, field: str) -> int:
    if isinstance(raw, bool):
        raise Mt5RateNormalizationError(f"row[{row_index}].{field}: invalid integer")
    try:
        value = index(raw)
    except Exception as exc:
        raise Mt5RateNormalizationError(
            f"row[{row_index}].{field}: invalid integer"
        ) from exc
    if value < 0:
        raise Mt5RateNormalizationError(f"row[{row_index}].{field}: negative")
    return value


def _timestamp(raw: object, row_index: int, timeframe: Timeframe) -> datetime:
    seconds = _whole_number(raw, row_index, "time")
    duration_seconds = int(timeframe.duration.total_seconds())
    if seconds % duration_seconds:
        raise Mt5RateNormalizationError(f"row[{row_index}].time: unaligned")
    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    except Exception as exc:
        raise Mt5RateNormalizationError(
            f"row[{row_index}].time: invalid timestamp"
        ) from exc


def _decimal(raw: object, row_index: int, field: str) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise Mt5RateNormalizationError(f"row[{row_index}].{field}: invalid decimal")
    try:
        value = Decimal(str(raw))
    except Exception as exc:
        raise Mt5RateNormalizationError(
            f"row[{row_index}].{field}: invalid decimal"
        ) from exc
    if not value.is_finite():
        raise Mt5RateNormalizationError(f"row[{row_index}].{field}: non-finite")
    return value


def normalize_mt5_rates(
    rows: Iterable[Mapping[str, object]],
    *,
    symbol: str,
    timeframe: Timeframe,
    now: datetime,
) -> tuple[Candle, ...]:
    if not isinstance(symbol, str) or not symbol or symbol != symbol.strip():
        raise _argument_error("symbol", "must be a non-empty stripped string")
    if not isinstance(timeframe, Timeframe):
        raise _argument_error("timeframe", "must be a Timeframe")
    if not isinstance(now, datetime) or now.tzinfo is not UTC:
        raise _argument_error("now", "must be timezone-aware UTC")

    try:
        iterator = iter(rows)
    except Exception as exc:
        raise Mt5RateNormalizationError("rows: not iterable") from exc

    normalized: list[Candle] = []
    row_index = 0
    while True:
        try:
            row = next(iterator)
        except StopIteration:
            break
        except Exception as exc:
            raise Mt5RateNormalizationError(
                f"row[{row_index}]: iteration failed"
            ) from exc
        timestamp = _timestamp(_row_value(row, row_index, "time"), row_index, timeframe)
        values = {
            field: _decimal(_row_value(row, row_index, field), row_index, field)
            for field in ("open", "high", "low", "close")
        }
        volume = Decimal(
            _whole_number(
                _row_value(row, row_index, "tick_volume"),
                row_index,
                "tick_volume",
            )
        )
        try:
            closed = timestamp + timeframe.duration <= now
        except Exception as exc:
            raise Mt5RateNormalizationError(
                f"row[{row_index}].invariant: close status"
            ) from exc
        try:
            normalized.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    open=values["open"],
                    high=values["high"],
                    low=values["low"],
                    close=values["close"],
                    volume=volume,
                    closed=closed,
                )
            )
        except ValueError as exc:
            raise Mt5RateNormalizationError(
                f"row[{row_index}].invariant: {exc}"
            ) from exc
        row_index += 1
    return tuple(normalized)
