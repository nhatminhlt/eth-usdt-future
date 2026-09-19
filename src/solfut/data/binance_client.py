"""REST client public cho Binance USDⓈ-M Futures — không cần API key.

Retry + rate-limit-aware (429/418 đọc Retry-After). Toàn bộ khoảng thời gian dùng milliseconds.
Luật 17: funding interval LUÔN đọc động qua fundingInfo — không hardcode 8h.
"""
from __future__ import annotations

import time

import requests
from loguru import logger

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


class BinanceFuturesPublic:
    def __init__(self, base_url: str = "https://fapi.binance.com", timeout: int = 20, max_retries: int = 6):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        last_err = None
        for attempt in range(self.max_retries):
            try:
                r = self.session.get(self.base + path, params=params, timeout=self.timeout)
            except requests.RequestException as e:  # mạng tạm thời
                last_err = e
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code in (429, 418):  # rate limit / banned
                wait = int(r.headers.get("Retry-After", 30))
                logger.warning(f"Rate-limited ({r.status_code}), chờ {wait}s…")
                time.sleep(wait)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code >= 500:
                last_err = RuntimeError(f"{r.status_code}: {r.text[:200]}")
                time.sleep(min(2 ** attempt, 30))
                continue
            r.raise_for_status()  # 4xx khác → lỗi thật, không retry
        raise RuntimeError(f"GET {path} thất bại sau {self.max_retries} lần: {last_err}")

    # ---- contract ----
    def exchange_info(self) -> dict:
        return self._get("/fapi/v1/exchangeInfo")

    def symbol_filters(self, symbol: str) -> dict:
        s = [x for x in self.exchange_info()["symbols"] if x["symbol"] == symbol][0]
        f = {flt["filterType"]: flt for flt in s["filters"]}
        return {
            "status": s["status"], "contract_type": s["contractType"],
            "tick_size": float(f["PRICE_FILTER"]["tickSize"]),
            "step_size": float(f["LOT_SIZE"]["stepSize"]),
            "min_qty": float(f["LOT_SIZE"]["minQty"]),
            "min_notional": float(f["MIN_NOTIONAL"]["notional"]),
        }

    # ---- funding (luật 17) ----
    def funding_info(self) -> list[dict]:
        return self._get("/fapi/v1/fundingInfo")

    def funding_interval_hours(self, symbol: str, default: int = 8) -> int:
        """SOLUSDT vắng mặt trong fundingInfo = đang mặc định 8h."""
        for row in self.funding_info():
            if row.get("symbol") == symbol:
                return int(row["fundingIntervalHours"])
        return default

    def funding_rate(self, symbol: str, start_ms: int | None = None,
                     end_ms: int | None = None, limit: int = 1000) -> list[dict]:
        params: dict = {"symbol": symbol, "limit": limit}
        if start_ms: params["startTime"] = start_ms
        if end_ms: params["endTime"] = end_ms
        return self._get("/fapi/v1/fundingRate", params)

    def funding_rate_all(self, symbol: str, start_ms: int) -> list[dict]:
        """Đầy đủ lịch sử funding từ start_ms (paginate)."""
        out, cursor = [], start_ms
        while True:
            batch = self.funding_rate(symbol, start_ms=cursor)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 1000:
                break
            cursor = batch[-1]["fundingTime"] + 1
            time.sleep(0.15)
        return out

    # ---- klines ----
    def klines(self, symbol: str, interval: str, start_ms: int | None = None,
               end_ms: int | None = None, limit: int = 1500) -> list[list]:
        params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms: params["startTime"] = start_ms
        if end_ms: params["endTime"] = end_ms
        return self._get("/fapi/v1/klines", params)

    def ping(self) -> bool:
        self._get("/fapi/v1/ping")
        return True
