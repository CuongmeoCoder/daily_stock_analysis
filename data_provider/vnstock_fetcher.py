# -*- coding: utf-8 -*-
"""Vietnam stock data fetcher backed by vnstock.

Only explicit exchange-prefixed symbols are supported, for example
``HOSE:VIC``. This avoids confusing Vietnamese tickers with US-style symbols.
"""

from __future__ import annotations

import contextlib
import io
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from src.services.market_symbol_utils import get_vn_ticker, is_vn_stock_symbol

from .base import BaseFetcher, DataFetchError
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote


logger = logging.getLogger(__name__)


_VN_STOCK_NAMES = {
    "HOSE:VIC": "Vingroup",
    "HOSE:VHM": "Vinhomes",
    "HOSE:VCB": "Vietcombank",
}


class VnstockFetcher(BaseFetcher):
    """Daily and best-effort realtime data for Vietnam stocks."""

    name = "VnstockFetcher"
    priority = 4

    @staticmethod
    def _is_supported(stock_code: str) -> bool:
        return is_vn_stock_symbol(stock_code)

    @staticmethod
    def _quote_for(stock_code: str):
        ticker = get_vn_ticker(stock_code)
        if not ticker:
            raise DataFetchError(f"Unsupported Vietnam stock symbol: {stock_code}")

        # vnstock prints notices during import/construction. Keep workflow logs
        # focused on analysis output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from vnstock.api.quote import Quote

            return Quote(symbol=ticker, source="VCI")

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if not self._is_supported(stock_code):
            raise DataFetchError(f"[Vnstock] unsupported symbol: {stock_code}")
        try:
            quote = self._quote_for(stock_code)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = quote.history(start=start_date, end=end_date, interval="1D")
        except Exception as exc:
            raise DataFetchError(f"[Vnstock] failed to fetch {stock_code}: {exc}") from exc
        if df is None or df.empty:
            raise DataFetchError(f"[Vnstock] no data for {stock_code}")
        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        normalized = df.copy()
        if "time" in normalized.columns:
            normalized = normalized.rename(columns={"time": "date"})
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(normalized.columns)
        if missing:
            raise DataFetchError(f"[Vnstock] missing columns for {stock_code}: {sorted(missing)}")
        normalized["amount"] = normalized.get("amount")
        if "amount" not in normalized.columns or normalized["amount"].isna().all():
            normalized["amount"] = normalized["close"] * normalized["volume"]
        normalized["pct_chg"] = normalized["close"].pct_change().fillna(0) * 100
        return normalized[["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]]

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        if not self._is_supported(stock_code):
            return None
        try:
            df = self.get_daily_data(stock_code, days=7)
            if df.empty:
                return None
            last = df.iloc[-1]
            prev_close = float(df.iloc[-2]["close"]) if len(df) >= 2 else None
            price = float(last["close"])
            change_amount = price - prev_close if prev_close else None
            change_pct = (change_amount / prev_close * 100) if prev_close else None
            return UnifiedRealtimeQuote(
                code=stock_code,
                name=self.get_stock_name(stock_code) or stock_code,
                source=RealtimeSource.FALLBACK,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                provider_timestamp=pd.to_datetime(last["date"]).isoformat(),
                market="vn",
                currency="VND",
                data_quality="partial",
                missing_fields=["intraday_quote"],
                price=price,
                change_pct=change_pct,
                change_amount=change_amount,
                volume=int(last["volume"]) if pd.notna(last["volume"]) else None,
                amount=float(last["amount"]) if pd.notna(last["amount"]) else None,
                open_price=float(last["open"]) if pd.notna(last["open"]) else None,
                high=float(last["high"]) if pd.notna(last["high"]) else None,
                low=float(last["low"]) if pd.notna(last["low"]) else None,
                pre_close=prev_close,
            )
        except Exception as exc:
            logger.debug("[Vnstock] realtime fallback failed for %s: %s", stock_code, exc)
            return None

    def get_stock_name(self, stock_code: str) -> str:
        normalized = (stock_code or "").strip().upper()
        return _VN_STOCK_NAMES.get(normalized, get_vn_ticker(normalized) or normalized)
