import time
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

# Seconds in each supported candle interval.
INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}

# The signal is shown as a pre-entry alert only during the final 10 seconds
# before the next candle starts.
PRE_ENTRY_SECONDS = 10

# After the candle boundary, keep ENTRY NOW valid briefly so the browser can
# refresh and confirm the entry without missing it because of network delay.
ENTRY_CONFIRM_SECONDS = 3


def _okx_symbol(symbol: str) -> str:
    clean = symbol.upper().replace("/", "").replace("-", "")
    if clean.endswith("USDT"):
        return f"{clean[:-4]}-USDT-SWAP"
    return clean


def _get_candles(symbol: str, interval: str, limit: int = 300):
    inst_id = _okx_symbol(symbol)
    bar = INTERVAL_MAP.get(interval)

    if bar is None:
        return None, {
            "error": "Unsupported interval for OKX",
            "interval": interval,
            "supported_intervals": sorted(INTERVAL_MAP.keys()),
        }

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

    rows = list(reversed(rows))
    parsed = []

    for row in rows:
        if len(row) < 9:
            continue

        parsed.append({
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "confirm": str(row[8]),
        })

    if len(parsed) < 200:
        return None, {
            "error": "Insufficient candle data",
            "received": len(parsed),
            "required": 200,
            "instrument": inst_id,
        }

    return parsed, None


def _indicator_frame(candles):
    df = pd.DataFrame(candles).copy()

    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    macd = ta.trend.MACD(
        df["close"],
        window_slow=26,
        window_fast=12,
        window_sign=9,
    )

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()

    df["atr"] = ta.volatility.average_true_range(
        df["high"],
        df["low"],
        df["close"],
        window=14,
    )

    return df.dropna().reset_index(drop=True)


def _score_row(row, prev):
    score = 0

    bullish_trend = row["ema20"] > row["ema50"] > row["ema200"]
    bearish_trend = row["ema20"] < row["ema50"] < row["ema200"]

    if bullish_trend:
        score += 30
    elif bearish_trend:
        score -= 30

    if row["close"] > row["ema20"]:
        score += 10
    elif row["close"] < row["ema20"]:
        score -= 10

    if 52 <= row["rsi"] <= 68:
        score += 15
    elif 32 <= row["rsi"] < 48:
        score -= 15
    elif 68 < row["rsi"] <= 75:
        score += 5
    elif 25 <= row["rsi"] < 32:
        score += 5
    elif row["rsi"] > 75:
        score -= 15
    elif row["rsi"] < 25:
        score += 15

    macd_bull = row["macd"] > row["macd_signal"]
    macd_bear = row["macd"] < row["macd_signal"]

    if macd_bull:
        score += 15
    elif macd_bear:
        score -= 15

    if row["macd"] > row["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        score += 10
    elif row["macd"] < row["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        score -= 10

    if (
        score >= 60
        and bullish_trend
        and row["close"] >= row["ema20"]
        and 45 <= row["rsi"] <= 75
    ):
        signal = "BUY"

    elif (
        score <= -60
        and bearish_trend
        and row["close"] <= row["ema20"]
        and 25 <= row["rsi"] <= 55
    ):
        signal = "SELL"

    else:
        signal = "WAIT"

    return int(score), signal


def _empirical_probability(df, current_score, current_signal):
    """
    Historical calibration using the same signal rules.

    This is an internal confidence estimate, not a guaranteed probability
    of profit.
    """
    if current_signal == "WAIT":
        return 50

    records = []

    # Closed historical candles only.
    for i in range(1, len(df) - 1):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        score, signal = _score_row(row, prev)

        if signal not in {"BUY", "SELL"}:
            continue

        next_close = float(df.iloc[i + 1]["close"])
        close_now = float(row["close"])

        won = (
            next_close > close_now
            if signal == "BUY"
            else next_close < close_now
        )

        if abs(score - current_score) <= 20 and signal == current_signal:
            records.append(int(won))

    if len(records) < 8:
        records = []

        for i in range(1, len(df) - 1):
            row = df.iloc[i]
            prev = df.iloc[i - 1]

            score, signal = _score_row(row, prev)

            if signal != current_signal:
                continue

            next_close = float(df.iloc[i + 1]["close"])
            close_now = float(row["close"])

            won = (
                next_close > close_now
                if signal == "BUY"
                else next_close < close_now
            )

            records.append(int(won))

    if len(records) >= 8:
        wins = sum(records)
        n = len(records)
        probability = round((wins + 1) / (n + 2) * 100)
        return max(50, min(90, probability))

    fallback = 50 + min(30, max(0, abs(current_score) - 60))
    return int(fallback)


def _entry_window(interval: str):
    """
    Return timing information relative to the next candle boundary.

    remaining:
      - seconds until the next candle opens.
      - At exactly 10..1 seconds: pre-entry window.
      - At 0..3 seconds after the boundary: entry confirmation window.
    """
    seconds = INTERVAL_SECONDS.get(interval)

    if seconds is None:
        return {
            "supported": False,
            "remaining": None,
            "next_candle_ts": None,
            "pre_entry": False,
            "entry_now": False,
        }

    now = time.time()
    next_candle_ts = (int(now) // seconds + 1) * seconds
    remaining = next_candle_ts - now

    # Immediately after a boundary, remaining is close to a full interval.
    # Detect the first few seconds of the newly opened candle separately.
    current_boundary = (int(now) // seconds) * seconds
    since_boundary = now - current_boundary

    entry_now = 0 <= since_boundary <= ENTRY_CONFIRM_SECONDS
    pre_entry = (
        not entry_now
        and 0 < remaining <= PRE_ENTRY_SECONDS
    )

    return {
        "supported": True,
        "remaining": max(0, int(remaining + 0.999)),
        "next_candle_ts": int(next_candle_ts),
        "pre_entry": pre_entry,
        "entry_now": entry_now,
    }


def analyze(symbol="BTCUSDT", interval="1h"):
    timing = _entry_window(interval)

    if not timing["supported"]:
        return {
            "error": "Unsupported interval for timed entry",
            "interval": interval,
            "supported_intervals": sorted(INTERVAL_SECONDS.keys()),
        }

    candles, error = _get_candles(symbol, interval)

    if error:
        return error

    df = _indicator_frame(candles)

    if len(df) < 3:
        return {
            "error": "Not enough data after indicator calculation"
        }

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score, signal = _score_row(last, prev)

    if last["ema20"] > last["ema50"] > last["ema200"]:
        trend = "UPTREND"
    elif last["ema20"] < last["ema50"] < last["ema200"]:
        trend = "DOWNTREND"
    else:
        trend = "SIDEWAYS"

    probability = _empirical_probability(
        df,
        score,
        signal,
    )

    # A normal signal is NOT an immediate entry anymore.
    # It becomes a timed entry only during the final 10 seconds before the
    # next candle. The browser polls this endpoint automatically.
    strong_signal = signal in {"BUY", "SELL"}
    pre_entry = bool(timing["pre_entry"] and strong_signal)
    entry_now = bool(timing["entry_now"] and strong_signal)

    if entry_now:
        trade_time = "NOW"
        entry = "NOW"

    elif pre_entry:
        trade_time = f"IN {timing['remaining']}s"
        entry = f"IN {timing['remaining']}s"

    else:
        trade_time = None
        entry = None

    return {
        "signal": signal if (pre_entry or entry_now) else "WAIT",
        "raw_signal": signal,
        "trend": trend,
        "score": int(score),
        "probability": int(probability),
        "entry": entry,
        "entry_now": entry_now,
        "pre_entry": pre_entry,
        "entry_countdown": timing["remaining"],
        "next_candle_ts": timing["next_candle_ts"],
        "trade_time": trade_time,
        "signal_live": True,
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
