# -*- coding: utf-8 -*-
"""Regression tests for explicit Vietnam market symbols."""

from unittest.mock import patch

import pandas as pd
import pytest

from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager, normalize_stock_code
from src.core.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE, get_market_for_stock
from src.market_context import detect_market
from src.services.market_symbol_utils import get_vn_ticker, is_vn_stock_symbol, normalize_vn_stock_symbol
from src.services.stock_code_utils import is_code_like, normalize_code


class _FakeFetcher(BaseFetcher):
    def __init__(self, name: str, should_fail: bool = False):
        self.name = name
        self.priority = 0
        self.calls = []
        self.should_fail = should_fail

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append(stock_code)
        if self.should_fail:
            raise DataFetchError(f"{self.name} should not be called for {stock_code}")
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-06-29")],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [100],
                "amount": [100.0],
                "pct_chg": [0.0],
            }
        )

    def get_stock_name(self, stock_code):
        self.calls.append(("name", stock_code))
        if self.should_fail:
            raise DataFetchError(f"{self.name} should not be called for {stock_code}")
        return "Vietnam Test Stock"


def test_normalize_and_detect_vn_exchange_prefixed_codes() -> None:
    assert normalize_vn_stock_symbol("hose:vic") == "HOSE:VIC"
    assert normalize_vn_stock_symbol(" hnx:shs ") == "HNX:SHS"
    assert normalize_vn_stock_symbol("upcom:bsr") == "UPCOM:BSR"
    assert normalize_vn_stock_symbol("VIC") is None

    assert normalize_stock_code("hose:vic") == "HOSE:VIC"
    assert detect_market("HOSE:VIC") == "vn"
    assert get_market_for_stock("HOSE:VIC") == "vn"
    assert is_vn_stock_symbol("HOSE:VCB") is True
    assert get_vn_ticker("HOSE:VCB") == "VCB"
    assert is_code_like("HOSE:VIC") is True
    assert normalize_code("HOSE:VIC") == "HOSE:VIC"


def test_data_fetcher_manager_routes_vn_daily_only_to_vnstock() -> None:
    efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
    yfinance = _FakeFetcher("YfinanceFetcher", should_fail=True)
    vnstock = _FakeFetcher("VnstockFetcher")
    manager = DataFetcherManager(fetchers=[efinance, yfinance, vnstock])

    with patch("data_provider.base.record_provider_run_started"), patch("data_provider.base.record_provider_run"):
        df, source = manager.get_daily_data("HOSE:VIC")

    assert source == "VnstockFetcher"
    assert not df.empty
    assert efinance.calls == []
    assert yfinance.calls == []
    assert vnstock.calls == ["HOSE:VIC"]


def test_data_fetcher_manager_routes_vn_names_only_to_vnstock() -> None:
    efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
    yfinance = _FakeFetcher("YfinanceFetcher", should_fail=True)
    vnstock = _FakeFetcher("VnstockFetcher")
    manager = DataFetcherManager(fetchers=[efinance, yfinance, vnstock])

    name = manager.get_stock_name("HOSE:VIC", allow_realtime=False)

    assert name == "Vietnam Test Stock"
    assert efinance.calls == []
    assert yfinance.calls == []
    assert vnstock.calls == [("name", "HOSE:VIC")]


def test_trading_calendar_registers_vn_timezone() -> None:
    assert MARKET_EXCHANGE["vn"] == ""
    assert MARKET_TIMEZONE["vn"] == "Asia/Ho_Chi_Minh"


def test_vn_is_first_class_on_write_paths() -> None:
    pytest.importorskip("sqlalchemy")

    from src.services.decision_signal_service import DecisionSignalService
    from src.services.intelligence_service import _ALLOWED_MARKETS
    from src.services.portfolio_service import VALID_MARKETS

    assert DecisionSignalService._normalize_market("vn") == "vn"
    assert "vn" in VALID_MARKETS
    assert "vn" in _ALLOWED_MARKETS
