import inspect
from datetime import UTC, datetime, timedelta
from threading import Thread, get_ident

import pytest

from xdirga_trading_core.market import (
    Mt5AccountEnvironment,
    Mt5MarketReader,
    Mt5MarketReadError,
    Mt5MarketReadErrorCode,
    Mt5ReaderConfig,
    ReasonCode,
    Timeframe,
    create_mt5_market_reader,
)
from xdirga_trading_core.market.mt5_reader import _create_mt5_market_reader

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Integral:
    def __init__(self, value: int) -> None:
        self.value = value

    def __index__(self) -> int:
        return self.value


class Account:
    def __init__(self, login: int = 123, trade_mode: int = 1) -> None:
        self.login = login
        self.trade_mode = trade_mode


class Symbol:
    def __init__(self, visible: bool = True) -> None:
        self.visible = visible


class FakeMt5:
    ACCOUNT_TRADE_MODE_DEMO = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    TIMEFRAME_M1 = 11
    TIMEFRAME_M5 = 12
    TIMEFRAME_M15 = 13
    TIMEFRAME_H1 = 14

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], int]] = []
        self.account: object = Account()
        self.symbol: object = Symbol()
        self.rates: object = [rate(1_767_225_600), rate(1_767_225_660)]
        self.initialize_result: object = True
        self.symbol_select_result: object = True
        self.last_error_result: object = (1, "identity password secret")
        self.fail: dict[str, BaseException] = {}

    def _call(self, name: str, *args: object, **kwargs: object) -> None:
        self.calls.append((name, args or (kwargs,), get_ident()))
        if name in self.fail:
            raise self.fail[name]

    def initialize(self, **kwargs: object) -> object:
        self._call("initialize", **kwargs)
        return self.initialize_result

    def account_info(self) -> object:
        self._call("account_info")
        return self.account

    def symbol_select(self, symbol: str, enabled: bool) -> object:
        self._call("symbol_select", symbol, enabled)
        return self.symbol_select_result

    def symbol_info(self, symbol: str) -> object:
        self._call("symbol_info", symbol)
        return self.symbol

    def copy_rates_from_pos(self, *args: object) -> object:
        self._call("copy_rates_from_pos", *args)
        return self.rates

    def last_error(self) -> object:
        self._call("last_error")
        return self.last_error_result

    def shutdown(self) -> None:
        self._call("shutdown")


def rate(time: int, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "time": time,
        "open": 1,
        "high": 2,
        "low": 0,
        "close": 1,
        "tick_volume": 1,
    }
    value.update(changes)
    return value


def config(**changes: object) -> Mt5ReaderConfig:
    values: dict[str, object] = {
        "terminal_path": None,
        "expected_login": 123,
        "server": None,
        "expected_environment": Mt5AccountEnvironment.DEMO,
        "symbol": "EURUSD",
    }
    values.update(changes)
    return Mt5ReaderConfig(**values)  # type: ignore[arg-type]


def reader(
    fake: FakeMt5 | None = None, **changes: object
) -> tuple[Mt5MarketReader, FakeMt5]:
    fake = fake or FakeMt5()
    return _create_mt5_market_reader(config(**changes), fake), fake


def error(code: Mt5MarketReadErrorCode, call) -> Mt5MarketReadError:
    with pytest.raises(Mt5MarketReadError) as caught:
        call()
    assert caught.value.code is code
    return caught.value


def test_public_api_error_enum_and_exact_signatures() -> None:
    assert {code.value for code in Mt5MarketReadErrorCode} == {
        "PACKAGE_UNAVAILABLE",
        "INITIALIZATION_FAILED",
        "ACCOUNT_UNAVAILABLE",
        "ACCOUNT_MISMATCH",
        "ENVIRONMENT_MISMATCH",
        "SYMBOL_UNAVAILABLE",
        "RATES_UNAVAILABLE",
        "NORMALIZATION_FAILED",
        "LIFECYCLE_ERROR",
    }
    assert (
        str(inspect.signature(Mt5MarketReader))
        == "(config: xdirga_trading_core.market.mt5_reader.Mt5ReaderConfig) -> None"
    )
    assert (
        str(inspect.signature(Mt5MarketReader.start))
        == "(self, *, password: str | None = None) -> None"
    )
    read = inspect.signature(Mt5MarketReader.read)
    assert list(read.parameters) == ["self", "timeframe", "now", "max_age"]
    assert read.parameters["now"].kind is inspect.Parameter.KEYWORD_ONLY
    assert read.parameters["max_age"].kind is inspect.Parameter.KEYWORD_ONLY
    assert (
        Mt5MarketReadError(Mt5MarketReadErrorCode.RATES_UNAVAILABLE).code
        is Mt5MarketReadErrorCode.RATES_UNAVAILABLE
    )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("terminal_path", " path "),
        ("terminal_path", 1),
        ("server", ""),
        ("server", 1),
        ("expected_login", True),
        ("expected_login", 1.5),
        ("expected_environment", "DEMO"),
        ("symbol", " EURUSD"),
        ("symbol", 1),
        ("history_count", True),
        ("history_count", 1),
        ("history_count", 5001),
        ("history_count", 2.5),
    ],
)
def test_config_strictness_and_integral_normalization(field: str, bad: object) -> None:
    with pytest.raises(ValueError):
        config(**{field: bad})
    value = config(
        expected_login=Integral(123),
        history_count=Integral(2),
        terminal_path="path",
        server="server",
    )
    assert value.expected_login == 123 and value.history_count == 2
    text = repr(value)
    assert (
        all(secret not in text for secret in ("123", "path", "server"))
        and "EURUSD" in text
    )


def test_start_rejects_malformed_password_before_mt5_call() -> None:
    value, fake = reader()

    with pytest.raises(ValueError, match="password must be None or a string"):
        value.start(password=1)  # type: ignore[arg-type]

    assert fake.calls == []


@pytest.mark.parametrize(
    "optional",
    [
        {},
        {"terminal_path": "path"},
        {"server": "server"},
        {"terminal_path": "path", "server": "server"},
    ],
)
def test_start_initialization_kwargs_and_both_environments(
    optional: dict[str, str],
) -> None:
    value, fake = reader(**optional)
    value.start(password="secret")
    kwargs = fake.calls[0][1][0]
    assert kwargs == {
        "login": 123,
        **({"path": "path"} if "terminal_path" in optional else {}),
        **({"server": "server"} if "server" in optional else {}),
        "password": "secret",
    }
    value.stop()
    real, module = reader(expected_environment=Mt5AccountEnvironment.REAL)
    module.account = Account(trade_mode=module.ACCOUNT_TRADE_MODE_REAL)
    real.start()


@pytest.mark.parametrize(
    "change,code",
    [
        (
            lambda f: setattr(f, "initialize_result", False),
            Mt5MarketReadErrorCode.INITIALIZATION_FAILED,
        ),
        (
            lambda f: setattr(f, "account", None),
            Mt5MarketReadErrorCode.ACCOUNT_UNAVAILABLE,
        ),
        (
            lambda f: setattr(f, "account", Account(9)),
            Mt5MarketReadErrorCode.ACCOUNT_MISMATCH,
        ),
        (
            lambda f: setattr(f.account, "trade_mode", 9),
            Mt5MarketReadErrorCode.ENVIRONMENT_MISMATCH,
        ),
        (
            lambda f: setattr(f, "ACCOUNT_TRADE_MODE_DEMO", None),
            Mt5MarketReadErrorCode.ENVIRONMENT_MISMATCH,
        ),
        (
            lambda f: setattr(f, "symbol", None),
            Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE,
        ),
        (
            lambda f: setattr(f.symbol, "visible", False),
            Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE,
        ),
    ],
)
def test_start_failure_mapping_cleanup_and_sanitization(
    change, code: Mt5MarketReadErrorCode
) -> None:
    value, fake = reader()
    change(fake)
    fake.fail["shutdown"] = RuntimeError("password identity secret")
    caught = error(code, value.start)
    assert caught.__cause__ is None and "secret" not in str(caught).lower()
    if code is not Mt5MarketReadErrorCode.INITIALIZATION_FAILED:
        assert caught.__notes__ == ["MT5 cleanup failed"]
    if (
        fake.calls
        and fake.calls[0][0] == "initialize"
        and fake.initialize_result is not False
    ):
        assert fake.calls[-1][0] == "shutdown"


@pytest.mark.parametrize(
    "method", ["initialize", "account_info", "symbol_select", "symbol_info"]
)
def test_start_ordinary_errors_are_sanitized(method: str) -> None:
    value, fake = reader()
    fake.fail[method] = RuntimeError("password identity secret")
    caught = error(Mt5MarketReadErrorCode.INITIALIZATION_FAILED, value.start)
    assert caught.__cause__ is None and "secret" not in str(caught).lower()


def test_lifecycle_owner_restart_and_keyboard_interrupt() -> None:
    value, fake = reader()
    error(
        Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    value.start()
    errors: list[Mt5MarketReadError] = []
    thread = Thread(
        target=lambda: errors.append(
            error(
                Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
                lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
            )
        )
    )
    thread.start()
    thread.join()
    assert {call[2] for call in fake.calls} == {get_ident()}
    value.stop()
    value.stop()
    value.start()
    fake.fail["copy_rates_from_pos"] = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        value.read(Timeframe.M1, now=NOW, max_age=timedelta())


@pytest.mark.parametrize(
    "rows,reasons",
    [
        ([], (ReasonCode.EMPTY, ReasonCode.COUNT_MISMATCH)),
        (
            [rate(1_767_225_600), rate(1_767_225_660)],
            (
                ReasonCode.LATEST_UNCLOSED,
                ReasonCode.UNCLOSED_CANDLES,
                ReasonCode.COUNT_MISMATCH,
            ),
        ),
        (
            [rate(1_767_225_480), rate(1_767_225_600)],
            (
                ReasonCode.MISSING_TIMESTAMPS,
                ReasonCode.LATEST_UNCLOSED,
                ReasonCode.UNCLOSED_CANDLES,
                ReasonCode.COUNT_MISMATCH,
            ),
        ),
        (
            [rate(1_767_225_660), rate(1_767_225_600)],
            (
                ReasonCode.INVALID_ORDER,
                ReasonCode.LATEST_UNCLOSED,
                ReasonCode.UNCLOSED_CANDLES,
                ReasonCode.COUNT_MISMATCH,
            ),
        ),
        (
            [rate(1_767_225_600), rate(1_767_225_600)],
            (
                ReasonCode.INVALID_ORDER,
                ReasonCode.DUPLICATE_TIMESTAMPS,
                ReasonCode.LATEST_UNCLOSED,
                ReasonCode.UNCLOSED_CANDLES,
                ReasonCode.COUNT_MISMATCH,
            ),
        ),
    ],
)
def test_read_maps_rates_preserves_order_and_composes_validation(
    rows: list[dict[str, object]], reasons: tuple[ReasonCode, ...]
) -> None:
    value, fake = reader()
    value.start()
    fake.rates = rows
    result = value.read(Timeframe.M1, now=NOW, max_age=timedelta(minutes=1))
    assert result.validation.reason_codes == reasons
    assert fake.calls[-1][1] == ("EURUSD", 11, 1, 256)


def test_read_errors_arguments_constants_normalizer_and_last_error() -> None:
    value, fake = reader()
    value.start()
    calls = len(fake.calls)
    for args in (
        ("M1", NOW, timedelta()),
        (Timeframe.M1, datetime(2026, 1, 1), timedelta()),
        (Timeframe.M1, NOW, timedelta(seconds=-1)),
    ):
        error(
            Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
            lambda args=args: value.read(args[0], now=args[1], max_age=args[2]),
        )
    assert len(fake.calls) == calls
    fake.TIMEFRAME_M1 = None
    error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    fake.TIMEFRAME_M1 = 11
    fake.rates = None
    fake.fail["last_error"] = RuntimeError("secret")
    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    assert caught.__cause__ is None
    fake.rates = [rate(0, open="bad")]
    normalization_error = error(
        Mt5MarketReadErrorCode.NORMALIZATION_FAILED,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    assert normalization_error.__cause__.__class__.__name__ == (
        "Mt5RateNormalizationError"
    )
    assert normalization_error.__cause__.__cause__ is None
    assert "bad" not in "".join(
        str(item) for item in normalization_error.__cause__.args
    )


def test_package_absence_and_static_surface(monkeypatch) -> None:
    value = create_mt5_market_reader(config())
    monkeypatch.setattr(
        "xdirga_trading_core.market.mt5_reader._load_module",
        lambda: (_ for _ in ()).throw(ImportError("secret")),
    )
    assert (
        error(Mt5MarketReadErrorCode.PACKAGE_UNAVAILABLE, value.start).__cause__ is None
    )
    import xdirga_trading_core.market.mt5_reader as module

    source = inspect.getsource(module).lower()
    assert not any(
        name in source
        for name in (
            "order_send",
            "order_check",
            "positions_get",
            "orders_get",
            "history_deals_get",
            "symbol_info_tick",
            "copy_ticks",
            "submit",
            "execute",
            "passthrough",
        )
    )
    assert "f\"timeframe_" not in source
    assert "getattr(module" not in source


@pytest.mark.parametrize(
    "timeframe,constant",
    [
        (Timeframe.M1, 11),
        (Timeframe.M5, 12),
        (Timeframe.M15, 13),
        (Timeframe.H1, 14),
    ],
)
def test_read_uses_exact_fixed_timeframe_mapping(
    timeframe: Timeframe, constant: int
) -> None:
    value, fake = reader(history_count=2)
    value.start()
    fake.rates = []

    value.read(timeframe, now=NOW, max_age=timedelta())

    assert fake.calls[-1][1] == ("EURUSD", constant, 1, 2)


@pytest.mark.parametrize("malformed", [None, True, 1.5])
def test_read_rejects_malformed_timeframe_constants(malformed: object) -> None:
    value, fake = reader()
    value.start()
    fake.TIMEFRAME_M1 = malformed

    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )

    assert caught.__cause__ is None
    assert not any(call[0] == "copy_rates_from_pos" for call in fake.calls)


def test_read_rejects_missing_and_raising_timeframe_constants() -> None:
    class MissingTimeframe(FakeMt5):
        TIMEFRAME_M1 = None

        def __getattribute__(self, name: str) -> object:
            if name == "TIMEFRAME_M1":
                raise RuntimeError("identity password secret")
            return super().__getattribute__(name)

    value, fake = reader(MissingTimeframe())
    value.start()
    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    assert caught.__cause__ is None and "secret" not in repr(caught)
    assert not any(call[0] == "copy_rates_from_pos" for call in fake.calls)


def production_traceback_values(error: BaseException) -> list[object]:
    retained: list[object] = []
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename.replace("\\", "/").endswith(
            "/market/mt5_reader.py"
        ):
            retained.extend(traceback.tb_frame.f_locals.values())
        traceback = traceback.tb_next
    return retained


def retained_exception_values(error: BaseException) -> list[object]:
    retained: list[object] = []
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        retained.extend(vars(current).values())
        retained.extend(current.args)
        traceback = current.__traceback__
        while traceback is not None:
            retained.extend(traceback.tb_frame.f_locals.values())
            traceback = traceback.tb_next
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return retained


def test_direct_hostile_native_code_is_rejected_without_hooks_or_retention() -> None:
    hooks: list[str] = []

    class HostileInt(int):
        def __repr__(self) -> str:
            hooks.append("repr")
            return "DIRECT_NATIVE_MARKER"

        def __str__(self) -> str:
            hooks.append("str")
            return "DIRECT_NATIVE_MARKER"

        def __int__(self) -> int:
            hooks.append("int")
            return 10004

    hostile = HostileInt(10004)
    caught = Mt5MarketReadError(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE, native_code=hostile
    )

    assert caught.native_code is None
    assert hooks == []
    assert hostile not in retained_exception_values(caught)
    assert "DIRECT_NATIVE_MARKER" not in str(caught)
    assert "DIRECT_NATIVE_MARKER" not in repr(caught)


def test_error_code_requires_exact_enum_without_hostile_hooks() -> None:
    hooks: list[str] = []

    class HostileCode(str):
        def __hash__(self) -> int:
            hooks.append("hash")
            return super().__hash__()

        def __eq__(self, other: object) -> bool:
            hooks.append("eq")
            return super().__eq__(other)

        def __repr__(self) -> str:
            hooks.append("repr")
            return "HOSTILE_CODE_MARKER"

        def __str__(self) -> str:
            hooks.append("str")
            return "HOSTILE_CODE_MARKER"

    hostile = HostileCode(Mt5MarketReadErrorCode.RATES_UNAVAILABLE.value)
    with pytest.raises(
        TypeError, match="code must be a Mt5MarketReadErrorCode"
    ) as caught:
        Mt5MarketReadError(hostile)  # type: ignore[arg-type]

    assert hooks == []
    assert hostile not in production_traceback_values(caught.value)
    valid = Mt5MarketReadError(Mt5MarketReadErrorCode.RATES_UNAVAILABLE)
    assert valid.code is Mt5MarketReadErrorCode.RATES_UNAVAILABLE


def test_bounded_error_state_resists_assignment_and_dictionary_injection() -> None:
    caught = Mt5MarketReadError(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE, native_code=10004
    )
    original = (caught.code, caught.native_code, caught.args, str(caught), repr(caught))

    for name, replacement in (
        ("code", Mt5MarketReadErrorCode.LIFECYCLE_ERROR),
        ("native_code", 9),
        ("args", ("MUTATED",)),
        ("_code", Mt5MarketReadErrorCode.LIFECYCLE_ERROR),
        ("_native_code", 9),
        ("_message", "MUTATED"),
    ):
        with pytest.raises(AttributeError):
            setattr(caught, name, replacement)
    caught.__dict__.update(
        code=Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
        native_code=9,
        args=("MUTATED",),
        _code=Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
        _native_code=9,
        _message="MUTATED",
    )

    assert (
        caught.code,
        caught.native_code,
        caught.args,
        str(caught),
        repr(caught),
    ) == original


def test_bounded_error_state_resists_ordinary_deletion() -> None:
    caught = Mt5MarketReadError(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE, native_code=10004
    )
    original = (caught.code, caught.native_code, caught.args, str(caught), repr(caught))

    for name in (
        "code",
        "native_code",
        "args",
        "_code",
        "_native_code",
        "_message",
        "_code_value",
        "_native_code_value",
        "_message_value",
    ):
        with pytest.raises(AttributeError):
            delattr(caught, name)

    assert (
        caught.code,
        caught.native_code,
        caught.args,
        str(caught),
        repr(caught),
    ) == original


def test_hostile_int_native_code_is_rejected_without_invoking_hooks() -> None:
    hooks: list[str] = []

    class HostileInt(int):
        def __repr__(self) -> str:
            hooks.append("repr")
            return "NATIVE_CODE_MARKER"

        def __str__(self) -> str:
            hooks.append("str")
            return "NATIVE_CODE_MARKER"

        def __int__(self) -> int:
            hooks.append("int")
            return 10004

        def __index__(self) -> int:
            hooks.append("index")
            return 10004

    value, fake = reader()
    value.start()
    fake.rates = None
    fake.last_error_result = (HostileInt(10004), "NATIVE_CODE_MARKER")

    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )

    assert caught.native_code is None
    assert hooks == []
    surfaces = (
        str(caught),
        repr(caught),
        str(caught.args),
        str(caught.__notes__) if hasattr(caught, "__notes__") else "",
        str(caught.__cause__),
        str(caught.__context__),
        str(vars(caught)),
    )
    assert all("NATIVE_CODE_MARKER" not in surface for surface in surfaces)
    traceback_values = [
        retained
        for frame_info in inspect.getinnerframes(caught.__traceback__)
        for retained in frame_info.frame.f_locals.values()
    ]
    assert fake.last_error_result[0] not in traceback_values


def test_none_rates_exposes_only_safe_native_code() -> None:
    value, fake = reader()
    value.start()
    fake.rates = None
    fake.last_error_result = (10004, "login=123 password=secret server=private")

    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )

    assert caught.native_code == 10004
    with pytest.raises(AttributeError):
        caught.native_code = 9  # type: ignore[misc]
    with pytest.raises(AttributeError):
        caught._native_code = 9
    with pytest.raises(AttributeError):
        caught.code = Mt5MarketReadErrorCode.LIFECYCLE_ERROR
    assert caught.code is Mt5MarketReadErrorCode.RATES_UNAVAILABLE
    assert caught.native_code == 10004
    assert "10004" in repr(caught)
    assert not any(word in repr(caught) for word in ("123", "secret", "private"))


@pytest.mark.parametrize(
    "last_error",
    [
        (True, "password secret"),
        (1.5, "password secret"),
        ("10004", "password secret"),
        {"code": 10004, "password": "secret"},
        (10004, object()),
    ],
)
def test_malformed_last_error_has_no_evidence_or_leak(last_error: object) -> None:
    value, fake = reader()
    value.start()
    fake.rates = None
    fake.last_error_result = last_error

    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )

    assert caught.native_code is None
    assert caught.__cause__ is None
    assert "secret" not in repr(caught).lower()


def test_stop_shutdown_error_clears_state_and_allows_restart() -> None:
    value, fake = reader()
    value.start()
    fake.fail["shutdown"] = RuntimeError("identity password secret")

    caught = error(Mt5MarketReadErrorCode.LIFECYCLE_ERROR, value.stop)

    assert caught.__cause__ is None and "secret" not in repr(caught)
    value.stop()
    fake.fail.pop("shutdown")
    value.start()
    value.stop()


def test_cross_thread_stop_rejected_before_mt5_call() -> None:
    value, fake = reader()
    value.start()
    calls = len(fake.calls)
    errors: list[Mt5MarketReadError] = []
    thread = Thread(
        target=lambda: errors.append(
            error(Mt5MarketReadErrorCode.LIFECYCLE_ERROR, value.stop)
        )
    )

    thread.start()
    thread.join()

    assert len(errors) == 1 and len(fake.calls) == calls
    value.stop()


@pytest.mark.parametrize("failure", [RuntimeError("identity password secret")])
def test_copy_rates_ordinary_exception_is_sanitized(failure: BaseException) -> None:
    value, fake = reader()
    value.start()
    fake.fail["copy_rates_from_pos"] = failure

    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )

    assert caught.__cause__ is None and "secret" not in repr(caught)


def test_copy_rates_system_exit_propagates() -> None:
    value, fake = reader()
    value.start()
    fake.fail["copy_rates_from_pos"] = SystemExit("stop")

    with pytest.raises(SystemExit, match="stop"):
        value.read(Timeframe.M1, now=NOW, max_age=timedelta())


@pytest.mark.parametrize("failure", [False, RuntimeError("identity password secret")])
def test_symbol_select_false_or_exception_is_sanitized(failure: object) -> None:
    value, fake = reader()
    if isinstance(failure, BaseException):
        fake.fail["symbol_select"] = failure
    else:
        fake.symbol_select_result = failure

    caught = error(
        Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE
        if failure is False
        else Mt5MarketReadErrorCode.INITIALIZATION_FAILED,
        value.start,
    )

    assert caught.__cause__ is None and "secret" not in repr(caught)


def test_start_without_password_omits_password_kwarg() -> None:
    value, fake = reader(terminal_path="path", server="server")

    value.start()

    assert fake.calls[0][1][0] == {"login": 123, "path": "path", "server": "server"}


@pytest.mark.parametrize("returned_count", [255, 257])
def test_read_count_mismatch_preserves_full_order_and_evidence(
    returned_count: int,
) -> None:
    value, fake = reader(history_count=256)
    value.start()
    start = 1_767_225_600
    fake.rates = [rate(start + 60 * index) for index in range(returned_count)]

    result = value.read(
        Timeframe.M1,
        now=NOW + timedelta(minutes=returned_count + 1),
        max_age=timedelta(minutes=2),
    )

    assert result.requested_count == 256
    assert tuple(candle.timestamp for candle in result.candles) == tuple(
        datetime.fromtimestamp(start + 60 * index, UTC)
        for index in range(returned_count)
    )
    assert result.validation.expected_count == 256
    assert result.validation.actual_count == returned_count
    assert result.validation.all_closed
    assert not result.validation.count_complete
    assert not result.validation.trusted
    assert result.validation.reason_codes == (ReasonCode.COUNT_MISMATCH,)
    assert [call[1] for call in fake.calls if call[0] == "copy_rates_from_pos"] == [
        ("EURUSD", 11, 1, 256)
    ]


def test_read_active_exact_count_preserves_sequence_without_count_mismatch() -> None:
    value, fake = reader(history_count=2)
    value.start()
    fake.rates = [rate(1_767_225_540), rate(1_767_225_600)]

    result = value.read(Timeframe.M1, now=NOW, max_age=timedelta(minutes=1))

    assert result.validation.expected_count == 2
    assert result.validation.actual_count == 2
    assert result.validation.count_complete
    assert not result.validation.all_closed
    assert not result.validation.trusted
    assert result.validation.reason_codes == (
        ReasonCode.LATEST_UNCLOSED,
        ReasonCode.UNCLOSED_CANDLES,
    )
    assert [call[1] for call in fake.calls if call[0] == "copy_rates_from_pos"] == [
        ("EURUSD", 11, 1, 2)
    ]


def test_read_empty_preserves_count_evidence_and_single_fetch() -> None:
    value, fake = reader(history_count=2)
    value.start()
    fake.rates = []

    result = value.read(Timeframe.M1, now=NOW, max_age=timedelta())

    assert result.candles == ()
    assert result.requested_count == 2
    assert result.validation.expected_count == 2
    assert result.validation.actual_count == 0
    assert not result.validation.count_complete
    assert not result.validation.all_closed
    assert not result.validation.trusted
    assert result.validation.reason_codes == (
        ReasonCode.EMPTY,
        ReasonCode.COUNT_MISMATCH,
    )
    assert [call[1] for call in fake.calls if call[0] == "copy_rates_from_pos"] == [
        ("EURUSD", 11, 1, 2)
    ]


def test_read_complete_result_and_trusted_closed_contiguous_candles() -> None:
    value, fake = reader(history_count=2)
    value.start()
    fake.rates = [rate(1_767_225_420), rate(1_767_225_480)]

    result = value.read(Timeframe.M1, now=NOW, max_age=timedelta(minutes=2))

    assert result.symbol == "EURUSD"
    assert result.timeframe is Timeframe.M1
    assert result.requested_count == 2
    assert result.observed_at is NOW
    assert isinstance(result.candles, tuple) and len(result.candles) == 2
    assert result.validation.trusted is True
    assert result.validation.reason_codes == ()


def test_stale_candles_return_normal_untrusted_result() -> None:
    value, fake = reader(history_count=2)
    value.start()
    fake.rates = [rate(1_767_225_000), rate(1_767_225_060)]

    result = value.read(Timeframe.M1, now=NOW, max_age=timedelta(minutes=1))

    assert result.validation.trusted is False
    assert ReasonCode.STALE_LATEST in result.validation.reason_codes


@pytest.mark.parametrize(
    "method,operation",
    [
        ("initialize", "start"),
        ("account_info", "start"),
        ("copy_rates_from_pos", "read"),
        ("shutdown", "stop"),
    ],
)
def test_sanitized_mt5_failures_retain_no_raw_context(
    method: str, operation: str
) -> None:
    marker = f"RAW_{method.upper()}_MARKER"
    value, fake = reader(terminal_path="PATH_MARKER", server="SERVER_MARKER")
    fake.fail[method] = RuntimeError(marker)
    if operation != "start":
        value.start(password="PASSWORD_MARKER")
    caught = error(
        Mt5MarketReadErrorCode.INITIALIZATION_FAILED
        if operation == "start"
        else Mt5MarketReadErrorCode.RATES_UNAVAILABLE
        if operation == "read"
        else Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
        value.start
        if operation == "start"
        else (
            lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta())
            if operation == "read"
            else value.stop()
        ),
    )

    assert caught.__cause__ is None and caught.__context__ is None
    rendered = " ".join(
        type(item).__name__ + str(item)
        for item in retained_exception_values(caught)
    )
    assert not any(
        secret in rendered
        for secret in (marker, "PATH_MARKER", "SERVER_MARKER", "PASSWORD_MARKER")
    )


@pytest.mark.parametrize(
    "failure_kind,expected",
    [
        ("login_property", Mt5MarketReadErrorCode.INITIALIZATION_FAILED),
        ("login_mismatch", Mt5MarketReadErrorCode.ACCOUNT_MISMATCH),
        ("environment_mismatch", Mt5MarketReadErrorCode.ENVIRONMENT_MISMATCH),
        ("visible_property", Mt5MarketReadErrorCode.INITIALIZATION_FAILED),
        ("invisible", Mt5MarketReadErrorCode.SYMBOL_UNAVAILABLE),
    ],
)
def test_boot_assertions_release_raw_account_and_symbol_payloads(
    failure_kind: str, expected: Mt5MarketReadErrorCode
) -> None:
    hooks: list[str] = []

    class HostileAccount:
        @property
        def login(self) -> int:
            if failure_kind == "login_property":
                raise RuntimeError("ACCOUNT_PAYLOAD_MARKER")
            return 999 if failure_kind == "login_mismatch" else 123

        @property
        def trade_mode(self) -> int:
            return 999 if failure_kind == "environment_mismatch" else 1

        def __repr__(self) -> str:
            hooks.append("account_repr")
            return "ACCOUNT_PAYLOAD_MARKER"

    class HostileSymbol:
        @property
        def visible(self) -> bool:
            if failure_kind == "visible_property":
                raise RuntimeError("SYMBOL_PAYLOAD_MARKER")
            return failure_kind != "invisible"

        def __repr__(self) -> str:
            hooks.append("symbol_repr")
            return "SYMBOL_PAYLOAD_MARKER"

    value, fake = reader()
    account = HostileAccount()
    symbol = HostileSymbol()
    fake.account = account
    fake.symbol = symbol
    caught = error(expected, value.start)

    assert hooks == []
    retained = retained_exception_values(caught)
    assert account not in retained and symbol not in retained
    assert caught.__cause__ is None and caught.__context__ is None


@pytest.mark.parametrize("stage", ["lookup", "call", "truth"])
@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
def test_initialize_base_exception_scrubs_rolls_back_and_retries(
    stage: str, failure_type: type[BaseException]
) -> None:
    failure = failure_type("INITIALIZE_BASE_MARKER")

    class Result:
        def __bool__(self) -> bool:
            if stage == "truth":
                raise failure
            return True

    class Module(FakeMt5):
        fail_lookup = stage == "lookup"

        def __getattribute__(self, name: str) -> object:
            if name == "initialize" and object.__getattribute__(self, "fail_lookup"):
                raise failure
            return super().__getattribute__(name)

        def initialize(self, **kwargs: object) -> object:
            self._call("initialize", **kwargs)
            if stage == "call":
                raise failure
            return self.initialize_result

    module = Module()
    module.initialize_result = Result()
    value, _ = reader(module, terminal_path="PATH_MARKER", server="SERVER_MARKER")
    with pytest.raises(failure_type) as caught:
        value.start(password="PASSWORD_MARKER")
    retained = production_traceback_values(caught.value)
    assert not any(
        marker in str(item)
        for item in retained
        for marker in ("PASSWORD_MARKER", "PATH_MARKER", "SERVER_MARKER")
    )
    module.fail_lookup = False
    module.initialize_result = True
    stage = "retry"
    value.start()
    value.stop()


@pytest.mark.parametrize("method", ["account_info", "symbol_info"])
def test_post_initialize_base_exception_cleans_up_and_retries(method: str) -> None:
    value, fake = reader()
    fake.fail[method] = SystemExit("POST_INITIALIZE_MARKER")
    with pytest.raises(SystemExit):
        value.start()
    assert [call[0] for call in fake.calls].count("shutdown") == 1
    fake.fail.pop(method)
    value.start()
    value.stop()


@pytest.mark.parametrize("stage", ["lookup", "truth"])
def test_initialize_boundary_detaches_rolls_back_and_allows_retry(stage: str) -> None:
    marker = f"INITIALIZE_{stage.upper()}_MARKER"

    class HostileResult:
        def __bool__(self) -> bool:
            raise RuntimeError(marker)

        def __repr__(self) -> str:
            raise AssertionError("representation invoked")

    class InitializeBoundary(FakeMt5):
        lookup_failure = stage == "lookup"

        def __getattribute__(self, name: str) -> object:
            if name == "initialize" and object.__getattribute__(self, "lookup_failure"):
                raise RuntimeError(marker)
            return super().__getattribute__(name)

        def initialize(self, **kwargs: object) -> object:
            self._call("initialize", **kwargs)
            return self.initialize_result

    module = InitializeBoundary()
    module.initialize_result = HostileResult() if stage == "truth" else True
    value, _ = reader(module, terminal_path="PATH_MARKER", server="SERVER_MARKER")
    caught = error(
        Mt5MarketReadErrorCode.INITIALIZATION_FAILED,
        lambda: value.start(password="PASSWORD_MARKER"),
    )
    assert caught.__cause__ is None and caught.__context__ is None
    assert not any(
        secret in str(item)
        for item in retained_exception_values(caught)
        for secret in (marker, "PATH_MARKER", "SERVER_MARKER", "PASSWORD_MARKER")
    )
    module.lookup_failure = False
    module.initialize_result = True
    value.start()
    value.stop()


def test_shutdown_lookup_failure_stop_clears_state_and_allows_restart() -> None:
    class ShutdownLookup(FakeMt5):
        lookup_failure = False

        def __getattribute__(self, name: str) -> object:
            if name == "shutdown" and object.__getattribute__(self, "lookup_failure"):
                raise RuntimeError("SHUTDOWN_LOOKUP_MARKER")
            return super().__getattribute__(name)

    module = ShutdownLookup()
    value, _ = reader(module)
    value.start()
    module.lookup_failure = True
    caught = error(Mt5MarketReadErrorCode.LIFECYCLE_ERROR, value.stop)
    assert caught.__cause__ is None and caught.__context__ is None
    assert not any(
        "SHUTDOWN_LOOKUP_MARKER" in str(item)
        for item in retained_exception_values(caught)
    )
    value.stop()
    module.lookup_failure = False
    value.start()
    value.stop()


def test_cleanup_lookup_failure_preserves_primary_and_allows_retry() -> None:
    class CleanupLookup(FakeMt5):
        lookup_failure = True

        def __getattribute__(self, name: str) -> object:
            if name == "shutdown" and object.__getattribute__(self, "lookup_failure"):
                raise RuntimeError("CLEANUP_LOOKUP_MARKER")
            return super().__getattribute__(name)

    module = CleanupLookup()
    module.account = None
    value, _ = reader(module)
    caught = error(Mt5MarketReadErrorCode.ACCOUNT_UNAVAILABLE, value.start)
    assert caught.__notes__ == ["MT5 cleanup failed"]
    assert caught.__cause__ is None and caught.__context__ is None
    assert not any(
        "CLEANUP_LOOKUP_MARKER" in str(item)
        for item in retained_exception_values(caught)
    )
    module.lookup_failure = False
    module.account = Account()
    value.start()
    value.stop()


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), SystemExit()])
def test_initialize_truth_base_exception_propagates(failure: BaseException) -> None:
    class BaseFailure:
        def __bool__(self) -> bool:
            raise failure

    value, fake = reader()
    fake.initialize_result = BaseFailure()
    with pytest.raises(type(failure)):
        value.start()


@pytest.mark.parametrize("stage", ["lookup", "call"])
@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
def test_partial_cleanup_base_exception_attempted_once_and_retryable(
    stage: str, failure_type: type[BaseException]
) -> None:
    failure = failure_type("CLEANUP_BASE_MARKER")

    class Module(FakeMt5):
        lookups = 0
        invocations = 0
        fail_cleanup = True

        def __getattribute__(self, name: str) -> object:
            if name == "shutdown" and object.__getattribute__(self, "fail_cleanup"):
                object.__setattr__(self, "lookups", self.lookups + 1)
                if stage == "lookup":
                    raise failure
            return super().__getattribute__(name)

        def shutdown(self) -> None:
            self.invocations += 1
            if self.fail_cleanup:
                raise failure
            super().shutdown()

    module = Module()
    module.account = None
    value, _ = reader(module)
    with pytest.raises(failure_type) as caught:
        value.start()
    assert caught.value is failure
    assert module.lookups == 1
    assert module.invocations == (stage == "call")
    assert caught.value.__context__ is None
    module.fail_cleanup = False
    module.account = Account()
    value.start()
    value.stop()


def test_repeated_start_scrubs_password_and_preserves_active_state() -> None:
    value, fake = reader()
    value.start()
    marker = "REPEATED_PASSWORD_MARKER"
    caught = error(
        Mt5MarketReadErrorCode.LIFECYCLE_ERROR,
        lambda: value.start(password=marker),
    )
    assert marker not in production_traceback_values(caught)
    assert caught.__cause__ is None and caught.__context__ is None
    value.stop()
    assert fake.calls[-1][0] == "shutdown"


def test_malformed_password_scrubs_object_without_hooks_or_mt5_call() -> None:
    hooks: list[str] = []

    class HostilePassword:
        def __repr__(self) -> str:
            hooks.append("repr")
            return "MALFORMED_PASSWORD_MARKER"

        def __str__(self) -> str:
            hooks.append("str")
            return "MALFORMED_PASSWORD_MARKER"

    hostile = HostilePassword()
    value, fake = reader()
    with pytest.raises(ValueError) as caught:
        value.start(password=hostile)  # type: ignore[arg-type]
    assert hostile not in production_traceback_values(caught.value)
    assert hooks == [] and fake.calls == []


def test_package_and_constant_failures_retain_no_raw_context(monkeypatch) -> None:
    value = create_mt5_market_reader(config())
    monkeypatch.setattr(
        "xdirga_trading_core.market.mt5_reader._load_module",
        lambda: (_ for _ in ()).throw(ImportError("PACKAGE_MARKER")),
    )
    package_error = error(Mt5MarketReadErrorCode.PACKAGE_UNAVAILABLE, value.start)
    assert package_error.__cause__ is None and package_error.__context__ is None
    assert not any(
        "PACKAGE_MARKER" in str(item)
        for item in retained_exception_values(package_error)
    )

    class RaisingConstant(FakeMt5):
        def __getattribute__(self, name: str) -> object:
            if name == "TIMEFRAME_M1":
                raise RuntimeError("CONSTANT_MARKER")
            return super().__getattribute__(name)

    active, _ = reader(RaisingConstant())
    active.start()
    constant_error = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: active.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    assert constant_error.__cause__ is None and constant_error.__context__ is None
    assert not any(
        "CONSTANT_MARKER" in str(item)
        for item in retained_exception_values(constant_error)
    )


def test_last_error_and_partial_cleanup_failures_retain_no_raw_context() -> None:
    value, fake = reader()
    value.start()
    fake.rates = None
    fake.fail["last_error"] = RuntimeError("LAST_ERROR_MARKER")
    caught = error(
        Mt5MarketReadErrorCode.RATES_UNAVAILABLE,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )
    assert caught.__cause__ is None and caught.__context__ is None
    assert not any(
        "LAST_ERROR_MARKER" in str(item)
        for item in retained_exception_values(caught)
    )

    boot, module = reader()
    module.fail["account_info"] = RuntimeError("PRIMARY_MARKER")
    module.fail["shutdown"] = RuntimeError("CLEANUP_MARKER")
    failed = error(Mt5MarketReadErrorCode.INITIALIZATION_FAILED, boot.start)
    assert failed.__cause__ is None and failed.__context__ is None
    assert failed.__notes__ == ["MT5 cleanup failed"]
    assert not any(
        marker in str(item)
        for item in retained_exception_values(failed)
        for marker in ("PRIMARY_MARKER", "CLEANUP_MARKER")
    )


def test_normalization_has_only_approved_detached_cause() -> None:
    value, fake = reader()
    value.start()
    fake.rates = [rate(0, open=object())]

    caught = error(
        Mt5MarketReadErrorCode.NORMALIZATION_FAILED,
        lambda: value.read(Timeframe.M1, now=NOW, max_age=timedelta()),
    )

    assert caught.__context__ is None
    assert caught.__cause__.__class__.__name__ == "Mt5RateNormalizationError"
    assert caught.__cause__.__cause__ is None
    assert caught.__cause__.__context__ is None


def test_read_never_accesses_fake_mutation_or_generic_gateway_surface() -> None:
    class ReadOnlyTrap(FakeMt5):
        def __getattr__(self, name: str) -> object:
            forbidden = (
                "order",
                "position",
                "deal",
                "tick",
                "gateway",
                "passthrough",
                "send",
                "execute",
            )
            if any(part in name.lower() for part in forbidden):
                raise AssertionError(name)
            raise AttributeError(name)

    value, fake = reader(ReadOnlyTrap())
    value.start()
    value.read(Timeframe.M1, now=NOW, max_age=timedelta())
    value.stop()

    assert {call[0] for call in fake.calls} <= {
        "initialize",
        "account_info",
        "symbol_select",
        "symbol_info",
        "copy_rates_from_pos",
        "shutdown",
    }
