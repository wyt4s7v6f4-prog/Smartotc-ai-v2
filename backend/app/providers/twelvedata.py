import os

import pandas as pd
import requests
import ta


API_KEY = os.getenv("TWELVEDATA_API_KEY", "afdc8f80c3374bb7a5130679e76e57ae")


def get_forex_data(symbol="EUR/USD", interval="1min"):
    """Analyze Forex/OTC data from Twelve Data.

    Twelve Data does not provide a true 10-second series on this endpoint,
    so 10s/15s/30s requests are mapped to the available 1-minute candles.
    BUY/SELL results are treated as actionable at the moment the analysis
    response is generated and expose the same entry fields as the OKX path.
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

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": td_interval,
        "outputsize": 250,
        "apikey": API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return {
            "error": "Twelve Data request failed",
            "details": str(exc),
            "symbol": symbol,
            "interval": requested_interval,
        }
    except ValueError:
        return {
            "error": "Twelve Data returned non-JSON response",
            "symbol": symbol,
            "interval": requested_interval,
        }

    if "values" not in data:
        return {
            "error": "Twelve Data API error",
            "details": data,
            "symbol": symbol,
            "interval": requested_interval,
        }

    df = pd.DataFrame(data["values"])
    if len(df) < 60:
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

    macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
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

    score = 0

    if last["ema20"] > last["ema50"]:
        score += 25
    else:
        score -= 25

    if last["macd"] > last["macd_signal"]:
        score += 25
    else:
        score -= 25

    if 45 <= last["rsi"] <= 70:
        score += 25
    elif last["rsi"] < 45:
        score -= 10
    elif last["rsi"] > 70:
        score -= 10

    if last["close"] > last["ema20"]:
        score += 25
    else:
        score -= 25

    if score >= 50:
        signal = "BUY"
    elif score <= -50:
        signal = "SELL"
    else:
        signal = "WAIT"

    entry_now = signal in {"BUY", "SELL"}
    probability = min(95, max(50, 50 + int(abs(score) * 0.45)))

    return {
        "price": round(float(last["close"]), 5),
        "ema20": round(float(last["ema20"]), 5),
        "ema50": round(float(last["ema50"]), 5),
        "rsi": round(float(last["rsi"]), 2),
        "signal": signal,
        "score": int(score),
        "probability": probability,
        "trend": "BULLISH" if last["ema20"] > last["ema50"] else "BEARISH",
        "entry": "NOW" if entry_now else None,
        "entry_now": entry_now,
        "trade_time": "NOW" if entry_now else None,
        "interval": requested_interval,
        "data_interval": td_interval,
        "symbol": symbol,
        "source": "Twelve Data",
    }
