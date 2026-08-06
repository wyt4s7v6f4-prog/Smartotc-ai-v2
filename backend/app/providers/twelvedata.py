import requests
import pandas as pd
import ta

API_KEY ="afdc8f80c3374bb7a5130679e76e57ae"


def get_forex_data(symbol="EUR/USD", interval="1min"):

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
        "1d": "1day"
    }

    interval = interval_map.get(interval, "1min")

    url = (
        f"https://api.twelvedata.com/time_series"
        f"?symbol={symbol}"
        f"&interval={interval}"
        f"&outputsize=250"
        f"&apikey={API_KEY}"
    )

    data = requests.get(url, timeout=10).json()

    if "values" not in data:
        return {"error": data}

    df = pd.DataFrame(data["values"])

    df = df.iloc[::-1]

    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["open"] = df["open"].astype(float)

    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)

    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    macd = ta.trend.MACD(df["close"])

    df["macd"] = macd.macd()
    df["signal"] = macd.macd_signal()

    last = df.iloc[-1]

    signal = "WAIT"
    score = 0

    if last["ema20"] > last["ema50"]:
        score += 25

    if last["macd"] > last["signal"]:
        score += 25

    if 45 <= last["rsi"] <= 70:
        score += 25

    if last["close"] > last["ema20"]:
        score += 25

    if score >= 75:
        signal = "BUY"

    elif score <= 25:
        signal = "SELL"

    return {
        "price": round(last["close"],5),
        "ema20": round(last["ema20"],5),
        "ema50": round(last["ema50"],5),
        "rsi": round(last["rsi"],2),
        "signal": signal,
        "score": score,
        "trend": "BULLISH" if last["ema20"] > last["ema50"] else "BEARISH",
        "trade_time": interval
    }