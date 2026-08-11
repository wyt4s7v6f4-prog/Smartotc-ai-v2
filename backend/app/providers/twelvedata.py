import os
import time
import threading

import pandas as pd
import requests
import ta


API_KEY = os.getenv("TWELVEDATA_API_KEY", "afdc8f80c3374bb7a5130679e76e57ae")

# Twelve Data free/low-tier plans are rate-limited. The browser polls the
# backend frequently for the 10-second entry timer, so do not hit Twelve Data
# on every poll. Cache the calculated FX analysis briefly and reuse it during
# the same candle. If a 429 happens, serve the last good result instead of
# turning the UI into an ERROR.
CACHE_TTL_SECONDS = 30
_cache = {}
_cache_lock = threading.Lock()


def _cache_key(symbol, td_interval):
    return (symbol.upper().strip(), td_interval)


def _get_cached(key):
    with _cache_lock:
        item = _cache.get(key)
    if not item:
        return None
    saved_at, value = item
    if time.time() - saved_at <= CACHE_TTL_SECONDS:
        return dict(value)
    return None


def _set_cached(key, value):
    with _cache_lock:
        _cache[key] = (time.time(), dict(value))


def get_forex_data(symbol="EUR/USD", interval="1min"):
    """Analyze Forex/OTC data from Twelve Data with rate-limit protection.

    OTC is represented by the underlying FX pair. The data provider is called
    at most once per cache window; the web UI may poll much more frequently
    without consuming an API request on every timer tick.
    """

    interval_map = {
        "10s": "1min",
        "15s": "1min",
        "30s": "1min",
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
    }

    requested_interval = interval
    td_interval = interval_map.get(interval, "1min")
    key = _cache_key(symbol, td_interval)

    cached = _get_cached(key)
    if cached is not None:
        return cached

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": td_interval,
        "outputsize": 250,
        "apikey": API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
    except requests.RequestException as exc:
        cached = _get_cached(key)
        if cached is not None:
            return cached
        return {
            "error": "Twelve Data request failed",
            "details": str(exc),
            "symbol": symbol,
            "interval": requested_interval,
        }
    except ValueError:
        cached = _get_cached(key)
        if cached is not None:
            return cached
        return {
            "error": "Twelve Data returned non-JSON response",
            "symbol": symbol,
            "interval": requested_interval,
        }

    # Twelve Data can return HTTP 429 and/or an API-level status message.
    if response.status_code == 429 or str(data.get("status", "")).lower() == "error":
        message = data.get("message") or data.get("code") or "Too Many Requests"
        cached = _get_cached(key)
        if cached is not None:
            cached["rate_limited"] = True
            cached["rate_limit_message"] = str(message)
            return cached
        return {
            "error": "Twelve Data rate limit",
            "details": str(message),
            "symbol": symbol,
            "interval": requested_interval,
        }

    if response.status_code >= 400:
        cached = _get_cached(key)
        if cached is not None:
            return cached
        return {
            "error": "Twelve Data HTTP error",
            "status": response.status_code,
            "details": data,
            "symbol": symbol,
            "interval": requested_interval,
        }

    if "values" not in data:
        cached = _get_cached(key)
        if cached is not None:
            return cached
        return {
            "error": "Twelve Data API error",
            "details": data,
            "symbol": symbol,
        }

    df = pd.DataFrame(data["values"])
    if len(df) < 60:
        cached = _get_cached(key)
        if cached is not None:
            return cached
        return {
            "error": "Insufficient Forex candle data",
            "received": len(df),
            "required": 60,
            "symbol": symbol,
            "interval": requested_interval,
        }

    df = df.iloc[::-1].reset_index(drop=True)

    for column in ("close", "high", "low", "open"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["close", "high", "low", "open"]).reset_index(drop=True)

    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    macd = ta.trend.MACD(
        df["close"], window_slow=26, window_fast=12, window_sign=9
    )
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()

    df = df.dropna().reset_index(drop=True)
    if df.empty:
        return {
            "error": "Not enough data after indicator calculation",
            "symbol": symbol,
            "interval": requested_interval,
        }

    last = df.iloc[-1]

    # Directional scoring is deliberately less brittle than the old
    # all-or-nothing rules. A setup can still be bearish when EMA20 is only
    # marginally above EMA50 if price is below both averages and RSI/momentum
    # confirm the move. This prevents the AUTO mode from getting stuck on
    # NO STRONG SIGNAL for otherwise clear directional setups.
    score = 0

    if last["ema20"] > last["ema50"]:
        score += 25
    elif last["ema20"] < last["ema50"]:
        score -= 25

    if last["close"] > max(last["ema20"], last["ema50"]):
        score += 25
    elif last["close"] < min(last["ema20"], last["ema50"]):
        score -= 25
    elif last["close"] > last["ema20"]:
        score += 10
    else:
        score -= 10

    if last["macd"] > last["macd_signal"]:
        score += 20
    elif last["macd"] < last["macd_signal"]:
        score -= 20

    if 55 <= last["rsi"] <= 70:
        score += 20
    elif 30 <= last["rsi"] < 45:
        score -= 20
    elif last["rsi"] > 70:
        score += 8
    elif last["rsi"] < 30:
        score -= 8

    if len(df) >= 2:
        delta = float(last["close"] - df.iloc[-2]["close"])
        if delta > 0:
            score += 10
        elif delta < 0:
            score -= 10

    score = max(-100, min(100, int(score)))

    # 45 is the minimum directional threshold for the proxy feed. AUTO mode
    # applies an additional quality filter before opening a trade.
    if score >= 45:
        signal = "BUY"
    elif score <= -45:
        signal = "SELL"
    else:
        signal = "WAIT"

    probability = min(90, max(50, 50 + int(abs(score) * 0.40)))

    result = {
        "price": round(float(last["close"]), 5),
        "ema20": round(float(last["ema20"]), 5),
        "ema50": round(float(last["ema50"]), 5),
        "rsi": round(float(last["rsi"]), 2),
        "signal": signal,
        "score": int(score),
        "probability": probability,
        "trend": "BULLISH" if last["ema20"] > last["ema50"] else "BEARISH",
        "entry": None,
        "entry_now": False,
        "trade_time": None,
        "interval": requested_interval,
        "data_interval": td_interval,
        "symbol": symbol,
        "source": "Twelve Data",
    }

    _set_cached(key, result)
    return result
