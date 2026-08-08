from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from operator import index
from threading import get_ident
from typing import Any

from .models import Candle, Timeframe
from .mt5_rates import Mt5RateNormalizationError, normalize_mt5_rates
from .validation import ValidationResult, validate_candles


class Mt5AccountEnvironment(str, Enum):
    DEMO = "DEMO"
    REAL = "REAL"


class Mt5MarketReadErrorCode(str, Enum):
    PACKAGE_UNAVAILABLE = "PACKAGE_UNAVAILABLE"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"
    ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    SYMBOL_UNAVAILABLE = "SYMBOL_UNAVAILABLE"
    RATES_UNAVAILABLE = "RATES_UNAVAILABLE"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    LIFECYCLE_ERROR = "LIFECYCLE_ERROR"


@dataclass(frozen=True, slots=True)
class Mt5ReaderConfig:
    terminal_path: str | None = field(repr=False)
    expected_login: int = field(repr=False)
    server: str | None = field(repr=False)
    expected_environment: Mt5AccountEnvironment
    symbol: str
    history_count: int = 256

    def __post_init__(self) -> None:
        for name in ("terminal_path", "server"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value or value != value.strip()
            ):
                raise ValueError(f"{name} must be None or a non-empty stripped string")
        for name in ("expected_login", "history_count"):
            raw = getattr(self, name)
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be an integer")
            try:
                value = index(raw)
            except Exception:
                raise ValueError(f"{name} must be an integer") from None
            object.__setattr__(self, name, value)
        if not 2 <= self.history_count <= 5000:
            raise ValueError("history_count must be from 2 through 5000")
        if not isinstance(self.expected_environment, Mt5AccountEnvironment):
            raise ValueError("expected_environment must be a Mt5AccountEnvironment")
        if (
            not isinstance(self.symbol, str)
            or not self.symbol
            or self.symbol != self.symbol.strip()
        ):
            raise ValueError("symbol must be a non-empty stripped string")


class Mt5MarketReadError(RuntimeError):
    __slots__ = ("_code_value", "_native_code_value", "_message_value")

    def __init__(
        self, code: Mt5MarketReadErrorCode, *, native_code: int | None = None
    ) -> None:
        if type(code) is not Mt5MarketReadErrorCode:
            code = None  # type: ignore[assignment]
            raise TypeError("code must be a Mt5MarketReadErrorCode")
        canonical_code = native_code if type(native_code) is int else None
        message = {
            Mt5MarketReadErrorCode.PACKAGE_UNAVAILABLE: "MT5 package unavailable",
            Mt5MarketReadErrorCode.INITIALIZATION_FAILED: "MT5 initialization failed",
            Mt5MarketReadErrorCode.ACCOUNT_UNAVAILABLE: "MT5 account unavailable",
            Mt5MarketReadErrorCode.ACCOUNT_MISMATCH: "MT5 account mismatch",
            Mt5MarketReadErrorCode.ENVIRONMENT_MISMATCH: "MT5 environment mismatch",
            Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE: "MT5 symbol unavailable",
            Mt5MarketReadErrorCode.RATES_UNAVAILABLE: "MT5 rates unavailable",
            Mt5MarketReadErrorCode.NORMALIZATION_FAILED: (
                "MT5 rate normalization failed"
            ),
            Mt5MarketReadErrorCode.LIFECYCLE_ERROR: "MT5 reader lifecycle error",
        }[code]
        RuntimeError.__init__(self, message)
        object.__setattr__(self, "_code_value", code)
        object.__setattr__(self, "_native_code_value", canonical_code)
        object.__setattr__(self, "_message_value", message)

    def __setattr__(self, name: str, value: object) -> None:
        if name in {
            "code",
            "native_code",
            "args",
            "_code",
            "_native_code",
            "_message",
            "_code_value",
            "_native_code_value",
            "_message_value",
        }:
            raise AttributeError(f"{name} is immutable")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in {
            "code",
            "native_code",
            "args",
            "_code",
            "_native_code",
            "_message",
            "_code_value",
            "_native_code_value",
            "_message_value",
        }:
            raise AttributeError(f"{name} is immutable")
        super().__delattr__(name)

    @property
    def code(self) -> Mt5MarketReadErrorCode:
        return self._code_value

    @property
    def native_code(self) -> int | None:
        return self._native_code_value

    @property
    def args(self) -> tuple[str]:
        return (self._message_value,)

    def __str__(self) -> str:
        return self._message_value

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"native_code={self.native_code!r})"
        )


@dataclass(frozen=True, slots=True)
class MarketReadResult:
    symbol: str
    timeframe: Timeframe
    observed_at: datetime
    requested_count: int
    candles: tuple[Candle, ...]
    validation: ValidationResult


class Mt5MarketReader:
    def __init__(self, config: Mt5ReaderConfig) -> None:
        self._config = config
        self._module: Any | None = None
        self._owner: int | None = None
        self._started = False

    @classmethod
    def _with_module(cls, config: Mt5ReaderConfig, module: Any) -> "Mt5MarketReader":
        reader = cls(config)
        reader._module = module
        return reader

    def _require_owner(self) -> Any:
        if not self._started or self._owner != get_ident():
            raise Mt5MarketReadError(Mt5MarketReadErrorCode.LIFECYCLE_ERROR)
        return self._module

    def _cleanup(self) -> bool:
        return _shutdown(self._module)

    def start(self, *, password: str | None = None) -> None:
        if password is not None and not isinstance(password, str):
            password = None
            raise ValueError("password must be None or a string")
        if self._started or self._owner is not None:
            password = None
            raise Mt5MarketReadError(Mt5MarketReadErrorCode.LIFECYCLE_ERROR)
        self._owner = get_ident()
        initialized = False
        succeeded = False
        kwargs: dict[str, object] = {}
        try:
            if self._module is None:
                ok, loaded = _call(_load_module)
                if not ok:
                    raise Mt5MarketReadError(
                        Mt5MarketReadErrorCode.PACKAGE_UNAVAILABLE
                    )
                self._module = loaded
            kwargs["login"] = self._config.expected_login
            if self._config.terminal_path is not None:
                kwargs["path"] = self._config.terminal_path
            if self._config.server is not None:
                kwargs["server"] = self._config.server
            if password is not None:
                kwargs["password"] = password
            initialized = _initialize(self._module, kwargs)
            kwargs.clear()
            password = None
            if not initialized:
                raise Mt5MarketReadError(
                    Mt5MarketReadErrorCode.INITIALIZATION_FAILED
                )
            boot_error = _assert_boot(self._module, self._config)
            if boot_error is not None:
                error = Mt5MarketReadError(boot_error)
                initialized = False
                cleanup_ok = self._cleanup()
                if not cleanup_ok:
                    error.add_note("MT5 cleanup failed")
                raise error
            self._started = True
            succeeded = True
        finally:
            kwargs.clear()
            password = None
            if not succeeded:
                try:
                    if initialized:
                        self._cleanup()
                finally:
                    self._owner = None

    def read(
        self, timeframe: Timeframe, *, now: datetime, max_age: timedelta
    ) -> MarketReadResult:
        module = self._require_owner()
        if (
            not isinstance(timeframe, Timeframe)
            or not isinstance(now, datetime)
            or now.tzinfo is not UTC
            or not isinstance(max_age, timedelta)
            or max_age < timedelta()
        ):
            raise Mt5MarketReadError(Mt5MarketReadErrorCode.LIFECYCLE_ERROR)
        ok, rates_result = _call(_read_rates, module, timeframe, self._config)
        if not ok:
            raise Mt5MarketReadError(Mt5MarketReadErrorCode.RATES_UNAVAILABLE)
        rows = rates_result
        if rows is None:
            native_code = _safe_native_code(module)
            raise Mt5MarketReadError(
                Mt5MarketReadErrorCode.RATES_UNAVAILABLE, native_code=native_code
            )
        ok, normalized = _normalize(rows, self._config.symbol, timeframe, now)
        if not ok:
            public_error = Mt5MarketReadError(
                Mt5MarketReadErrorCode.NORMALIZATION_FAILED
            )
            raise public_error from normalized
        candles = normalized
        return MarketReadResult(
            self._config.symbol,
            timeframe,
            now,
            self._config.history_count,
            candles,
            validate_candles(candles, now=now, max_age=max_age),
        )

    def stop(self) -> None:
        if not self._started:
            return
        module = self._require_owner()
        self._started = False
        self._owner = None
        if not _shutdown(module):
            raise Mt5MarketReadError(Mt5MarketReadErrorCode.LIFECYCLE_ERROR)


def _assert_boot(
    module: Any, config: Mt5ReaderConfig
) -> Mt5MarketReadErrorCode | None:
    account = None
    symbol = None
    try:
        account = module.account_info()
        if account is None:
            return Mt5MarketReadErrorCode.ACCOUNT_UNAVAILABLE
        if account.login != config.expected_login:
            return Mt5MarketReadErrorCode.ACCOUNT_MISMATCH
        expected_mode = {
            Mt5AccountEnvironment.DEMO: module.ACCOUNT_TRADE_MODE_DEMO,
            Mt5AccountEnvironment.REAL: module.ACCOUNT_TRADE_MODE_REAL,
        }[config.expected_environment]
        if account.trade_mode != expected_mode:
            return Mt5MarketReadErrorCode.ENVIRONMENT_MISMATCH
        if not module.symbol_select(config.symbol, True):
            return Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE
        symbol = module.symbol_info(config.symbol)
        if symbol is None or not symbol.visible:
            return Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE
    except Exception:
        return Mt5MarketReadErrorCode.INITIALIZATION_FAILED
    finally:
        account = None
        symbol = None
    return None


def _initialize(module: Any, kwargs: dict[str, object]) -> bool:
    try:
        return bool(module.initialize(**kwargs))
    except Exception:
        return False


def _shutdown(module: Any) -> bool:
    try:
        module.shutdown()
    except Exception:
        return False
    return True


def _call(function: Any, *args: object, **kwargs: object) -> tuple[bool, Any]:
    try:
        return True, function(*args, **kwargs)
    except Exception:
        return False, None


def _read_rates(module: Any, timeframe: Timeframe, config: Mt5ReaderConfig) -> object:
    raw_timeframe = _map_timeframe(module, timeframe)
    if isinstance(raw_timeframe, bool):
        raise TypeError
    mapped = index(raw_timeframe)
    return module.copy_rates_from_pos(config.symbol, mapped, 0, config.history_count)


def _normalize(
    rows: object, symbol: str, timeframe: Timeframe, now: datetime
) -> tuple[bool, tuple[Candle, ...] | Mt5RateNormalizationError]:
    try:
        return True, normalize_mt5_rates(
            rows, symbol=symbol, timeframe=timeframe, now=now
        )
    except Mt5RateNormalizationError as error:
        message = str(error)
    return False, Mt5RateNormalizationError(message)


def _safe_native_code(module: Any) -> int | None:
    try:
        payload = module.last_error()
        if (
            isinstance(payload, tuple)
            and len(payload) == 2
            and type(payload[0]) is int
            and isinstance(payload[1], str)
        ):
            return payload[0]
    except Exception:
        pass
    return None


def _map_timeframe(module: Any, timeframe: Timeframe) -> object:
    if timeframe is Timeframe.M1:
        return module.TIMEFRAME_M1
    if timeframe is Timeframe.M5:
        return module.TIMEFRAME_M5
    if timeframe is Timeframe.M15:
        return module.TIMEFRAME_M15
    if timeframe is Timeframe.H1:
        return module.TIMEFRAME_H1
    raise KeyError


def _load_module() -> Any:
    try:
        import MetaTrader5
    except Exception:
        raise Mt5MarketReadError(Mt5MarketReadErrorCode.PACKAGE_UNAVAILABLE) from None
    return MetaTrader5


def _create_mt5_market_reader(config: Mt5ReaderConfig, module: Any) -> Mt5MarketReader:
    return Mt5MarketReader._with_module(config, module)


def create_mt5_market_reader(config: Mt5ReaderConfig) -> Mt5MarketReader:
    return Mt5MarketReader(config)
