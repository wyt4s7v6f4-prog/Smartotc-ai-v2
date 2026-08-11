import os
import time
import math
import requests
import pandas as pd
import ta


OKX_BASE_URL = "https://www.okx.com/api/v5/market/candles"

INTERVAL_MAP = {
    # 30s mode uses the latest 1-minute market candles for indicators;
    # the entry clock itself is synchronized to 30-second boundaries.
    "30s": "1m",
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
    "30s": 30,
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


TWELVEDATA_BASE_URL = "https://api.twelvedata.com/time_series"
# Set this in Render Environment Variables for OTC/Forex support.
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()

OTC_PAIRS = {
    "EUR/USD OTC": "EUR/USD",
    "GBP/USD OTC": "GBP/USD",
    "USD/JPY OTC": "USD/JPY",
    "USD/CHF OTC": "USD/CHF",
    "USD/CAD OTC": "USD/CAD",
    "AUD/USD OTC": "AUD/USD",
    "NZD/USD OTC": "NZD/USD",
    "EUR/JPY OTC": "EUR/JPY",
    "EUR/GBP OTC": "EUR/GBP",
    "EUR/CHF OTC": "EUR/CHF",
    "GBP/JPY OTC": "GBP/JPY",
    "AUD/JPY OTC": "AUD/JPY",
}

FOREX_PAIRS = {
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD",
    "AUD/USD", "NZD/USD", "EUR/JPY", "EUR/GBP", "EUR/CHF",
    "GBP/JPY", "AUD/JPY", "XAU/USD", "XAG/USD",
}

TD_INTERVAL_MAP = {
    # Twelve Data does not provide a native 30-second FX candle in this setup.
    # 30s mode therefore uses 1-minute FX candles for indicators while the
    # timed entry boundary is 30 seconds.
    "30s": "1min",
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
}


def _is_otc(symbol: str) -> bool:
    return symbol.upper().strip() in {k.upper() for k in OTC_PAIRS}


def _forex_symbol(symbol: str) -> str:
    clean = symbol.upper().strip()
    if clean in {k.upper() for k in OTC_PAIRS}:
        for display, pair in OTC_PAIRS.items():
            if clean == display.upper():
                return pair
    return clean.replace("-", "/")


def _get_twelvedata_candles(symbol: str, interval: str, limit: int = 250):
    if not TWELVEDATA_API_KEY:
        return None, {
            "error": "TWELVEDATA_API_KEY is not configured",
            "details": "Add TWELVEDATA_API_KEY to Render Environment Variables to enable OTC/Forex data.",
            "symbol": symbol,
        }

    td_interval = TD_INTERVAL_MAP.get(interval)
    if td_interval is None:
        return None, {
            "error": "Unsupported interval for OTC/Forex",
            "interval": interval,
            "supported_intervals": sorted(TD_INTERVAL_MAP.keys()),
        }

    pair = _forex_symbol(symbol)
    params = {
        "symbol": pair,
        "interval": td_interval,
        "outputsize": min(max(limit, 200), 5000),
        "apikey": TWELVEDATA_API_KEY,
    }

    try:
        response = requests.get(
            TWELVEDATA_BASE_URL,
            params=params,
            headers={"User-Agent": "SmartOTC-AI/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return None, {"error": "TwelveData request failed", "details": str(exc)}
    except ValueError:
        return None, {
            "error": "TwelveData returned non-JSON response",
            "status": response.status_code,
            "body": response.text[:500],
        }

    if "values" not in payload:
        return None, {
            "error": "TwelveData API error",
            "details": payload,
            "symbol": pair,
        }

    values = list(reversed(payload["values"] or []))
    parsed = []

    # TwelveData timestamps are exchange-local/UTC-like strings depending on
    # the endpoint. For timing we use the Render server clock, while candles
    # are used for the indicators.
    for i, row in enumerate(values):
        try:
            parsed.append({
                "time": row.get("datetime", i),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
                "confirm": "1",
            })
        except (KeyError, TypeError, ValueError):
            continue

    if len(parsed) < 200:
        return None, {
            "error": "Insufficient TwelveData candle data",
            "received": len(parsed),
            "required": 200,
            "symbol": pair,
            "interval": td_interval,
        }

    return parsed, None


def _okx_symbol(symbol: str) -> str:
    clean = symbol.upper().replace("/", "").replace("-", "")
    if clean.endswith("USDT"):
        return f"{clean[:-4]}-USDT-SWAP"
    return clean


def _get_candles(symbol: str, interval: str, limit: int = 300):
    # OTC and Forex are supplied by TwelveData. OTC here means the selected
    # OTC pair is analyzed from its underlying FX feed; broker-specific OTC
    # quotes are not publicly standardized.
    if _is_otc(symbol) or symbol.upper().strip() in FOREX_PAIRS:
        return _get_twelvedata_candles(symbol, interval, limit)

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
            "entry_ts": None,
            "expiry_ts": None,
            "duration_seconds": None,
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

    duration_seconds = seconds
    entry_ts = int(next_candle_ts) if pre_entry else (
        int(current_boundary) if entry_now else int(next_candle_ts)
    )
    expiry_ts = int(entry_ts + duration_seconds)

    return {
        "supported": True,
        "remaining": max(0, int(remaining + 0.999)),
        "next_candle_ts": int(next_candle_ts),
        "pre_entry": pre_entry,
        "entry_now": entry_now,
        "entry_ts": entry_ts,
        "expiry_ts": expiry_ts,
        "duration_seconds": duration_seconds,
    }


def _analyze_forex_via_project_provider(symbol: str, interval: str):
    """Use the project's existing TwelveData provider for OTC/Forex.

    This keeps OTC compatible with the existing Render project without
    duplicating the API-key handling. The provider supplies the live FX
    indicators; this function adds the same timed-entry fields used by the
    crypto analyzer.
    """
    try:
        from app.providers.twelvedata import get_forex_data
    except Exception as exc:
        return None, {
            "error": "OTC/Forex provider unavailable",
            "details": str(exc),
        }

    pair = _forex_symbol(symbol)
    try:
        result = get_forex_data(symbol=pair, interval=interval)
    except Exception as exc:
        return None, {
            "error": "OTC/Forex analysis failed",
            "details": str(exc),
            "symbol": pair,
        }

    if not isinstance(result, dict):
        return None, {
            "error": "OTC/Forex provider returned invalid data",
            "symbol": pair,
        }

    if result.get("error"):
        return None, result

    timing = _entry_window(interval)
    if not timing["supported"]:
        return None, {
            "error": "Unsupported interval for timed entry",
            "interval": interval,
        }

    raw_signal = str(result.get("signal", "WAIT")).upper()
    strong_signal = raw_signal in {"BUY", "SELL"}
    pre_entry = bool(timing["pre_entry"] and strong_signal)
    entry_now = bool(timing["entry_now"] and strong_signal)

    if entry_now:
        trade_time = f"{timing['duration_seconds']}s"
        entry = "NOW"
    elif pre_entry:
        trade_time = f"{timing['duration_seconds']}s"
        entry = f"IN {timing['remaining']}s"
    else:
        trade_time = None
        entry = None

    score = int(result.get("score", 0))
    probability = max(50, min(90, 50 + abs(score - 50) // 2))

    return {
        "signal": raw_signal if (pre_entry or entry_now) else "WAIT",
        "raw_signal": raw_signal,
        "trend": result.get("trend"),
        "score": score,
        "probability": probability,
        "entry": entry,
        "entry_now": entry_now,
        "pre_entry": pre_entry,
        "entry_countdown": timing["remaining"],
        "next_candle_ts": timing["next_candle_ts"],
        "entry_ts": timing["entry_ts"],
        "expiry_ts": timing["expiry_ts"],
        "duration_seconds": timing["duration_seconds"],
        "trade_duration": f'{timing["duration_seconds"]}s',
        "trade_time": trade_time,
        "signal_live": True,
        "price": result.get("price"),
        "ema20": result.get("ema20"),
        "ema50": result.get("ema50"),
        "rsi": result.get("rsi"),
        "interval": interval,
        "symbol": symbol.upper(),
        "source": "TwelveData FX proxy",
        "otc_proxy": bool(_is_otc(symbol)),
    }, None



AUTO_DURATIONS = (10, 30, 60, 120, 300, 600, 900)


def _auto_trade_plan(symbol: str, score: int = 0, probability: int = 50):
    """Choose an expiry automatically from the signal strength.

    The user selects only the market. Indicators are calculated from a 1-minute
    feed, while the trade expiry is selected from 10s/30s/1m/2m/5m/10m/15m.
    Stronger setups use shorter expiries; weaker-but-still-qualified setups use
    longer expiries. This is a heuristic, not a guarantee of outcome.
    """
    clean = symbol.upper().strip()
    abs_score = abs(int(score or 0))
    prob = int(probability or 50)

    if abs_score >= 90 and prob >= 85:
        duration = 10
    elif abs_score >= 85 and prob >= 82:
        duration = 30
    elif abs_score >= 80 and prob >= 78:
        duration = 60
    elif abs_score >= 76 and prob >= 75:
        duration = 120
    elif abs_score >= 73 and prob >= 72:
        duration = 300
    elif abs_score >= 70 and prob >= 70:
        duration = 600
    else:
        duration = 900

    return "1m", duration


def analyze_auto(symbol="BTCUSDT"):
    """Find the strongest current setup without asking the user for a timeframe.

    The engine checks 1m/5m/15m data, combines the directional scores, and
    chooses the expiry automatically. It never fabricates a direction when
    the evidence is mixed; instead it asks for another scan.
    """
    timeframes = ("1m", "5m", "15m")
    snapshots = []

    for tf in timeframes:
        try:
            item = analyze(symbol, tf, mode="manual")
        except Exception as exc:
            snapshots.append({"interval": tf, "error": str(exc)})
            continue
        if isinstance(item, dict) and not item.get("error"):
            snapshots.append(item)

    valid = [x for x in snapshots if x.get("score") is not None]
    if not valid:
        return {
            "error": "Unable to obtain market data for signal search",
            "symbol": symbol,
            "checked_timeframes": list(timeframes),
        }

    # Weight the shorter timeframe most heavily while requiring the broader
    # timeframes to contribute when they are available.
    weights = {"1m": 0.50, "5m": 0.30, "15m": 0.20}
    weighted_score = 0.0
    weight_total = 0.0
    for item in valid:
        w = weights.get(str(item.get("interval")), 0.0)
        weighted_score += float(item.get("score", 0)) * w
        weight_total += w

    combined_score = int(round(weighted_score / weight_total)) if weight_total else 0

    directions = {"BUY": 0.0, "SELL": 0.0}
    for item in valid:
        raw = str(item.get("raw_signal") or item.get("signal") or "WAIT").upper()
        if raw in directions:
            directions[raw] += weights.get(str(item.get("interval")), 0.0)

    if combined_score >= 45:
        direction = "BUY"
    elif combined_score <= -45:
        direction = "SELL"
    else:
        direction = "BUY" if directions["BUY"] > directions["SELL"] and directions["BUY"] >= 0.50 else (
            "SELL" if directions["SELL"] > directions["BUY"] and directions["SELL"] >= 0.50 else "WAIT"
        )

    probability = min(90, max(50, 50 + int(abs(combined_score) * 0.40)))

    # Agreement across timeframes is a quality bonus; disagreement is a
    # penalty. This makes the displayed confidence more conservative.
    agreeing = sum(
        weights.get(str(x.get("interval")), 0.0)
        for x in valid
        if str(x.get("raw_signal") or x.get("signal") or "WAIT").upper() == direction
    ) if direction in {"BUY", "SELL"} else 0.0
    if direction in {"BUY", "SELL"}:
        probability = min(90, probability + (5 if agreeing >= 0.80 else 0))
        if agreeing < 0.50:
            probability = max(50, probability - 8)

    min_score = 55
    min_probability = 68
    strong = direction in {"BUY", "SELL"} and abs(combined_score) >= min_score and probability >= min_probability

    # Use the snapshot with the strongest absolute score for the displayed
    # indicator values and price; the direction comes from the multi-timeframe
    # aggregate above.
    primary = max(valid, key=lambda x: abs(int(x.get("score", 0))))
    interval, duration = _auto_trade_plan(symbol, combined_score, probability)

    if not strong:
        primary.update({
            "mode": "auto",
            "signal": "WAIT",
            "raw_signal": direction if direction in {"BUY", "SELL"} else "WAIT",
            "score": combined_score,
            "probability": probability,
            "entry": None,
            "entry_now": False,
            "pre_entry": False,
            "entry_countdown": 0,
            "entry_ts": None,
            "expiry_ts": None,
            "duration_seconds": duration,
            "trade_duration": f"{duration}s",
            "trade_time": f"{duration}s",
            "signal_quality": "NO_STRONG_SETUP",
            "auto_timeframe": interval,
            "checked_timeframes": list(timeframes),
            "timeframe_scores": {str(x.get("interval")): int(x.get("score", 0)) for x in valid},
            "auto_plan": True,
        })
        return primary

    # Auto mode announces a qualified setup 10 seconds before entry.
    # Entry is synchronized to the next 10-second boundary so the browser
    # can show a real countdown instead of opening the trade immediately.
    now = time.time()
    entry_ts = (int(now) // PRE_ENTRY_SECONDS + 1) * PRE_ENTRY_SECONDS
    remaining = max(0, int(math.ceil(entry_ts - now)))
    since_boundary = now - ((int(now) // PRE_ENTRY_SECONDS) * PRE_ENTRY_SECONDS)
    entry_now = 0 <= since_boundary <= ENTRY_CONFIRM_SECONDS
    if entry_now:
        entry_ts = int(now)
        remaining = 0
    expiry = int(entry_ts + duration)
    primary.update({
        "mode": "auto",
        "signal": direction if entry_now else direction,
        "raw_signal": direction,
        "entry": "NOW" if entry_now else f"IN {remaining}s",
        "entry_now": entry_now,
        "pre_entry": not entry_now,
        "entry_countdown": remaining,
        "next_candle_ts": int(entry_ts),
        "entry_ts": int(entry_ts),
        "expiry_ts": expiry,
        "duration_seconds": duration,
        "trade_duration": f"{duration}s",
        "trade_time": f"{duration}s",
        "score": combined_score,
        "probability": probability,
        "signal_quality": "STRONG_SETUP",
        "auto_timeframe": interval,
        "checked_timeframes": list(timeframes),
        "timeframe_scores": {str(x.get("interval")): int(x.get("score", 0)) for x in valid},
        "auto_plan": True,
    })
    return primary


def analyze(symbol="BTCUSDT", interval="1h", mode="manual"):
    if str(mode).lower() == "auto" or str(interval).lower() == "auto":
        return analyze_auto(symbol)

    if _is_otc(symbol) or symbol.upper().strip() in FOREX_PAIRS:
        forex_result, forex_error = _analyze_forex_via_project_provider(symbol, interval)
        if forex_error:
            return forex_error
        return forex_result

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
        trade_time = f"{timing['duration_seconds']}s"
        entry = "NOW"

    elif pre_entry:
        trade_time = f"{timing['duration_seconds']}s"
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
        "entry_ts": timing["entry_ts"],
        "expiry_ts": timing["expiry_ts"],
        "duration_seconds": timing["duration_seconds"],
        "trade_duration": f'{timing["duration_seconds"]}s',
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
        "source": "TwelveData FX proxy" if (_is_otc(symbol) or symbol.upper().strip() in FOREX_PAIRS) else "OKX",
        "otc_proxy": bool(_is_otc(symbol)),
    }
