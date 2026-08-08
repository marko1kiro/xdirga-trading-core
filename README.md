# XDIRGA TRADING CORE

A fresh, trading-first foundation for a narrowly scoped automated trading core.

Phase 0 provides only a locally runnable and testable Python package. Trading is not yet enabled.

## Requirements

- Python 3.12 (`>=3.12,<3.13`)

## Setup

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
python -m xdirga_trading_core
```

## Test and lint

```bash
python -m pytest
python -m ruff check .
```

See [the pinned V4 salvage matrix](docs/v4-salvage-matrix.md) for Phase 0 provenance decisions.
