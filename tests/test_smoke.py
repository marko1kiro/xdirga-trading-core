import subprocess
import sys

import xdirga_trading_core


def run_module() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "xdirga_trading_core"],
        capture_output=True,
        check=False,
        text=True,
    )


def test_package_exposes_version() -> None:
    assert isinstance(xdirga_trading_core.__version__, str)
    assert xdirga_trading_core.__version__


def test_module_reports_safe_foundation_status() -> None:
    result = run_module()

    assert result.returncode == 0
    assert "XDIRGA TRADING CORE" in result.stdout
    assert "foundation ready" in result.stdout.lower()
    assert "trading disabled" in result.stdout.lower()
    assert result.stderr == ""


def test_module_output_is_deterministic() -> None:
    assert run_module().stdout == run_module().stdout
