"""Quotex OTC market-data adapter.

DATA ONLY: this module reads Quotex OTC candles and never places orders.
It uses the community API-Quotex async WebSocket client and a user-supplied
QUOTEX_SSID. If the session is not configured or the feed fails, the caller
gets an explicit error; it never silently falls back to TwelveData/FX proxy.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

OTC_INTERVAL_SECONDS = {
    "10s": 10,
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


def is_otc_symbol(symbol: str) -> bool:
    return "otc" in str(symbol).lower()


def normalize_otc_asset(symbol: str) -> str:
    s = str(symbol).strip().upper()
    s = s.replace(" OTC", "").replace("/", "").replace("-", "")
    return f"{s}_otc"


def interval_to_seconds(interval: str) -> int:
    key = str(interval).strip()
    if key not in OTC_INTERVAL_SECONDS:
        raise ValueError(
            f"Unsupported Quotex OTC interval: {key}. "
            f"Supported: {', '.join(OTC_INTERVAL_SECONDS)}"
        )
    return OTC_INTERVAL_SECONDS[key]


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _timestamp(value: Any) -> int:
    if hasattr(value, "timestamp"):
        return int(value.timestamp())
    if isinstance(value, str):
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except Exception:
            pass
    number = float(value)
    if number > 10_000_000_000:
        number /= 1000
    return int(number)


class QuotexOTCProvider:
    def __init__(self) -> None:
        self.ssid = os.getenv("QUOTEX_SSID", "").strip()
        self.is_demo = os.getenv("QUOTEX_IS_DEMO", "true").lower() in {
            "1", "true", "yes", "on"
        }
        self.region = os.getenv("QUOTEX_REGION", "").strip() or None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client: Any = None
        self._lock = threading.Lock()

    def configured(self) -> bool:
        return bool(os.getenv("QUOTEX_SSID", "").strip())

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop and self._loop.is_running():
            return self._loop

        ready = threading.Event()

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()
            loop.close()

        self._thread = threading.Thread(
            target=runner, name="quotex-otc-loop", daemon=True
        )
        self._thread.start()
        if not ready.wait(timeout=5) or not self._loop:
            raise RuntimeError("Failed to start Quotex OTC event loop")
        return self._loop

    async def _connect_async(self) -> None:
        self.ssid = os.getenv("QUOTEX_SSID", "").strip()
        if not self.ssid:
            raise RuntimeError(
                "QUOTEX_SSID is not configured. Add it to Render Environment Variables."
            )

        try:
            from api_quotex import AsyncQuotexClient
        except ImportError as exc:
            raise RuntimeError(
                "API-Quotex is not installed. Check backend/requirements.txt."
            ) from exc

        if self._client is None:
            kwargs = {"ssid": self.ssid, "is_demo": self.is_demo}
            if self.region:
                kwargs["region"] = self.region
            self._client = AsyncQuotexClient(**kwargs)

        connected = self._client.is_connected()
        if inspect.isawaitable(connected):
            connected = await connected
        if not connected:
            ok = await self._client.connect()
            if not ok:
                self._client = None
                raise RuntimeError("Quotex WebSocket authentication failed")

    async def _get_dataframe_async(self, asset: str, timeframe: int, count: int):
        """Prefer the documented DataFrame API, with a compatibility fallback."""
        await self._connect_async()

        method = getattr(self._client, "get_candles_dataframe", None)
        if method is not None:
            result = method(asset=asset, timeframe=timeframe, count=count)
            if inspect.isawaitable(result):
                result = await result
            return result

        method = getattr(self._client, "get_candles", None)
        if method is None:
            raise RuntimeError("Installed API-Quotex client has no candle method")

        # Different community releases have used different signatures.
        attempts = [
            lambda: method(asset=asset, timeframe=timeframe, count=count),
            lambda: method(asset, timeframe, count),
        ]
        last_exc: Optional[Exception] = None
        for attempt in attempts:
            try:
                result = attempt()
                if inspect.isawaitable(result):
                    result = await result
                return result
            except TypeError as exc:
                last_exc = exc
        raise last_exc or RuntimeError("Quotex candle request failed")

    async def _get_candles_async(
        self, symbol: str, interval: str, count: int
    ) -> List[Dict[str, float]]:
        asset = normalize_otc_asset(symbol)
        timeframe = interval_to_seconds(interval)
        raw = await self._get_dataframe_async(asset, timeframe, count)

        rows: List[Dict[str, float]] = []
        if hasattr(raw, "to_dict") and hasattr(raw, "columns"):
            # pandas DataFrame
            data = raw.reset_index().to_dict("records")
        elif isinstance(raw, dict):
            data = raw.get("data") or raw.get("candles") or []
        else:
            data = raw or []

        for candle in data:
            ts = _value(candle, "timestamp", "time", "datetime", default=0)
            op = _value(candle, "open")
            hi = _value(candle, "high")
            lo = _value(candle, "low")
            cl = _value(candle, "close")
            vol = _value(candle, "volume", default=0.0)
            if op is None or hi is None or lo is None or cl is None:
                continue
            rows.append({
                "time": _timestamp(ts),
                "open": float(op),
                "high": float(hi),
                "low": float(lo),
                "close": float(cl),
                "volume": float(vol or 0.0),
                "confirm": "1",
            })

        rows.sort(key=lambda x: x["time"])
        return rows[-count:]

    def get_candles(
        self, symbol: str, interval: str, count: int = 300
    ) -> Tuple[Optional[List[Dict[str, float]]], Optional[Dict[str, Any]]]:
        if not self.configured():
            return None, {
                "error": "Quotex OTC feed is not configured",
                "details": "Set QUOTEX_SSID in Render Environment Variables.",
                "source": "QUOTEX_OTC",
                "otc_proxy": False,
            }

        try:
            timeframe = interval_to_seconds(interval)
        except ValueError as exc:
            return None, {
                "error": str(exc),
                "source": "QUOTEX_OTC",
            }

        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._get_candles_async(symbol, interval, count), loop
        )
        try:
            rows = future.result(timeout=25)
        except Exception as exc:
            return None, {
                "error": "Quotex OTC request failed",
                "details": str(exc),
                "source": "QUOTEX_OTC",
                "asset": normalize_otc_asset(symbol),
                "interval": interval,
                "timeframe_seconds": timeframe,
                "otc_proxy": False,
            }

        if len(rows) < 50:
            return None, {
                "error": "Insufficient Quotex OTC candle data",
                "received": len(rows),
                "required": 50,
                "source": "QUOTEX_OTC",
                "asset": normalize_otc_asset(symbol),
                "interval": interval,
                "otc_proxy": False,
            }

        return rows, None


_PROVIDER = QuotexOTCProvider()


def get_otc_candles(
    symbol: str, interval: str, count: int = 300
) -> Tuple[Optional[List[Dict[str, float]]], Optional[Dict[str, Any]]]:
    return _PROVIDER.get_candles(symbol, interval, count)
