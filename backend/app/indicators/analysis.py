import requests
import pandas as pd
import ta


def analyze(symbol="BTCUSDT", interval="1h"):
    url = (
    f"https://api.bybit.com/v5/market/kline"
    f"?category=linear&symbol={symbol}&interval={interval}&limit=250"
)

    response = requests.get(url, timeout=10).json()

if response.get("retCode") != 0:
    return {"error": response}

candles = response["result"]["list"]

df = pd.DataFrame(candles, columns=[
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover"
])

df = df.iloc[:, :6]

df.columns = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float,
    })

    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)

    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()

    df = df.iloc[::-1].reset_index(drop=True)
    last = df.iloc[-1]

    signal = "WAIT"
    trend = "SIDEWAYS"
    score = 0

    if last["ema20"] > last["ema50"]:
        score += 20

    if last["ema50"] > last["ema200"]:
        score += 20

    if 50 <= last["rsi"] <= 65:
        score += 15

    elif 35 <= last["rsi"] < 50:
        score += 10

    if last["macd"] > last["macd_signal"]:
        score += 20

    if last["close"] > last["ema20"]:
        score += 15

    score = min(score, 100)

    if (
        last["ema20"] > last["ema50"]
        and 45 <= last["rsi"] <= 70
        and last["macd"] > last["macd_signal"]
    ):
        signal = "BUY"

    elif (
        last["ema20"] < last["ema50"]
        and 30 <= last["rsi"] <= 55
        and last["macd"] < last["macd_signal"]
    ):
        signal = "SELL"

    if last["ema20"] > last["ema50"] > last["ema200"]:
        trend = "BULLISH"

    elif last["ema20"] < last["ema50"] < last["ema200"]:
        trend = "BEARISH"

    trade_time = {
        "1m": "2-3 min",
        "5m": "10-15 min",
        "15m": "20-40 min",
        "1h": "2-4 h",
        "4h": "6-12 h",
        "1d": "1-3 days",
    }.get(interval, "-")

    return {
        "price": round(last["close"], 2),
        "ema20": round(last["ema20"], 2),
        "ema50": round(last["ema50"], 2),
        "ema200": round(last["ema200"], 2),
        "rsi": round(last["rsi"], 2),
        "macd": round(last["macd"], 2),
        "macd_signal": round(last["macd_signal"], 2),
        "signal": signal,
        "symbol": symbol,
        "interval": interval,
        "score": score,
        "trend": trend,
        "trade_time": trade_time,
    }