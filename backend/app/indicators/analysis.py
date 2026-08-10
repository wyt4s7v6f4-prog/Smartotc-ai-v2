import requests
import pandas as pd
import ta


OKX_BASE_URL = "https://www.okx.com/api/v5/market/candles"

INTERVAL_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
}


def _okx_symbol(symbol: str) -> str:
    """Convert BTCUSDT-style symbols to OKX perpetual swap instruments."""
    clean = symbol.upper().replace("/", "").replace("-", "")
    if clean.endswith("USDT"):
        base = clean[:-4]
        return f"{base}-USDT-SWAP"
    return clean


def _get_candles(symbol: str, interval: str, limit: int = 250):
    inst_id = _okx_symbol(symbol)
    bar = INTERVAL_MAP.get(interval, "1H")

    params = {
        "instId": inst_id,
        "bar": bar,
        "limit": min(max(limit, 200), 300),
    }
    headers = {"User-Agent": "SmartOTC-AI/1.0"}

    try:
        response = requests.get(
            OKX_BASE_URL,
            params=params,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, {"error": "OKX request failed", "details": str(exc)}

    try:
        payload = response.json()
    except ValueError:
        return None, {
            "error": "OKX returned non-JSON response",
            "status": response.status_code,
            "body": response.text[:500],
        }

    if payload.get("code") != "0":
        return None, {
            "error": "OKX API error",
            "code": payload.get("code"),
            "message": payload.get("msg", "Unknown OKX error"),
            "instrument": inst_id,
        }

    rows = payload.get("data") or []
    if not rows:
        return None, {
            "error": "No candle data returned by OKX",
            "instrument": inst_id,
            "interval": bar,
        }

    # OKX returns newest candles first. Keep chronological order for indicators.
    rows = list(reversed(rows))

    parsed = []
    for row in rows:
        if len(row) < 9:
            continue
        parsed.append(
            {
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "confirm": str(row[8]),
            }
        )

    # Exclude the currently forming candle so indicators are based on confirmed data.
    parsed = [row for row in parsed if row["confirm"] == "1"]

    if len(parsed) < 200:
        return None, {
            "error": "Insufficient candle data",
            "received": len(parsed),
            "required": 200,
            "instrument": inst_id,
        }

    return parsed, None


def analyze(symbol="BTCUSDT", interval="1h"):
    candles, error = _get_candles(symbol, interval)
    if error:
        return error

    df = pd.DataFrame(candles)
    df = df.drop(columns=["confirm"], errors="ignore")

    # Indicators used by the original project, with additional filters to
    # reduce weak/contradictory signals.
    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    macd = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["atr"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )

    # Drop incomplete indicator rows before evaluating the latest candle.
    df = df.dropna().reset_index(drop=True)
    if len(df) < 2:
        return {"error": "Not enough data after indicator calculation"}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0

    # Trend structure: strongest weight.
    bullish_trend = last["ema20"] > last["ema50"] > last["ema200"]
    bearish_trend = last["ema20"] < last["ema50"] < last["ema200"]

    if bullish_trend:
        score += 30
    elif bearish_trend:
        score -= 30

    # Price location relative to EMA20.
    if last["close"] > last["ema20"]:
        score += 10
    elif last["close"] < last["ema20"]:
        score -= 10

    # RSI: avoid chasing extreme conditions.
    if 50 <= last["rsi"] <= 65:
        score += 15
    elif 35 <= last["rsi"] < 50:
        score -= 5
    elif 65 < last["rsi"] <= 75:
        score += 5
    elif last["rsi"] < 30:
        score += 5
    elif last["rsi"] > 75:
        score -= 10

    # MACD direction and crossover confirmation.
    macd_bull = last["macd"] > last["macd_signal"]
    macd_bear = last["macd"] < last["macd_signal"]
    macd_cross_up = last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]
    macd_cross_down = last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]

    if macd_bull:
        score += 15
    elif macd_bear:
        score -= 15

    if macd_cross_up:
        score += 5
    elif macd_cross_down:
        score -= 5

    # Signal thresholds deliberately require confirmation.
    if score >= 60 and not (last["rsi"] > 75):
        signal = "BUY"
    elif score <= -60 and not (last["rsi"] < 25):
        signal = "SELL"
    else:
        signal = "WAIT"

    if bullish_trend:
        trend = "UPTREND"
    elif bearish_trend:
        trend = "DOWNTREND"
    else:
        trend = "SIDEWAYS"

    # Live-entry fields:
    # BUY/SELL means the signal is actionable immediately when returned.
    # WAIT means there is no confirmed entry right now.
    entry = "NOW" if signal in {"BUY", "SELL"} else None
    trade_time = "NOW" if signal in {"BUY", "SELL"} else None

    # Keep compatibility with existing callers and expose a simple probability
    # estimate derived from the strategy score. This is NOT a win-rate guarantee.
    probability = min(95, max(50, 50 + int(abs(score) * 0.75)))

    return {
        "signal": signal,
        "trend": trend,
        "score": int(score),
        "probability": probability,
        "entry": entry,
        "entry_now": signal in {"BUY", "SELL"},
        "trade_time": trade_time,
        "price": round(float(last["close"]), 8),
        "ema20": round(float(last["ema20"]), 8),
        "ema50": round(float(last["ema50"]), 8),
        "ema200": round(float(last["ema200"]), 8),
        "rsi": round(float(last["rsi"]), 2),
        "macd": round(float(last["macd"]), 8),
        "macd_signal": round(float(last["macd_signal"]), 8),
        "atr": round(float(last["atr"]), 8),
        "interval": interval,
        "symbol": symbol.upper(),
        "source": "OKX",
    }
