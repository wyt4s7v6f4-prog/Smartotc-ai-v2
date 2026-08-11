import math
import pandas as pd
import ta


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["bb_mid"] = ta.volatility.bollinger_mavg(out["close"], window=20)
    out["bb_high"] = ta.volatility.bollinger_hband(out["close"], window=20, window_dev=2)
    out["bb_low"] = ta.volatility.bollinger_lband(out["close"], window=20, window_dev=2)
    out["stoch_k"] = ta.momentum.stoch(out["high"], out["low"], out["close"], window=14, smooth_window=3)
    out["stoch_d"] = ta.momentum.stoch_signal(out["high"], out["low"], out["close"], window=14, smooth_window=3)
    out["adx"] = ta.trend.adx(out["high"], out["low"], out["close"], window=14)
    out["atr_pct"] = (out.get("atr", ta.volatility.average_true_range(out["high"], out["low"], out["close"], window=14)) / out["close"]) * 100
    if "volume" in out.columns:
        vol = pd.to_numeric(out["volume"], errors="coerce").fillna(0)
        out["volume_ratio"] = vol / vol.rolling(20).mean().replace(0, float("nan"))
    else:
        out["volume_ratio"] = float("nan")
    return out.dropna(subset=["bb_mid", "bb_high", "bb_low", "stoch_k", "stoch_d", "adx"]).reset_index(drop=True)


def _clamp(v, lo=-100, hi=100):
    return int(max(lo, min(hi, round(v))))


def technical_snapshot(df: pd.DataFrame):
    if len(df) < 30:
        return {"score": 0, "label": "NEUTRAL", "reasons": []}
    r = df.iloc[-1]
    p = df.iloc[-2]
    score = 0
    reasons = []

    if r["close"] > r["bb_mid"]:
        score += 10; reasons.append("Price above Bollinger mid")
    else:
        score -= 10; reasons.append("Price below Bollinger mid")

    if r["stoch_k"] > r["stoch_d"] and r["stoch_k"] < 80:
        score += 10; reasons.append("Stochastic bullish")
    elif r["stoch_k"] < r["stoch_d"] and r["stoch_k"] > 20:
        score -= 10; reasons.append("Stochastic bearish")

    if r["adx"] >= 20:
        if r["close"] > r["bb_mid"]:
            score += 8
        elif r["close"] < r["bb_mid"]:
            score -= 8
        reasons.append(f"ADX {r['adx']:.1f} trend strength")

    vr = r.get("volume_ratio")
    if pd.notna(vr):
        if vr >= 1.2 and r["close"] > p["close"]:
            score += 8; reasons.append("Volume expansion with bullish candle")
        elif vr >= 1.2 and r["close"] < p["close"]:
            score -= 8; reasons.append("Volume expansion with bearish candle")

    if r["close"] >= r["bb_high"]:
        score -= 5; reasons.append("At upper Bollinger band")
    elif r["close"] <= r["bb_low"]:
        score += 5; reasons.append("At lower Bollinger band")

    label = "BULLISH" if score >= 12 else "BEARISH" if score <= -12 else "NEUTRAL"
    return {"score": _clamp(score), "label": label, "reasons": reasons[:4]}


def smart_money_snapshot(df: pd.DataFrame):
    if len(df) < 20:
        return {"score": 0, "structure": "NEUTRAL", "liquidity": "NONE", "order_block": "NONE", "fvg": "NONE", "zone": "EQUILIBRIUM", "reasons": []}

    r = df.iloc[-1]
    recent = df.iloc[-21:-1]
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    score = 0
    reasons = []

    bullish_bos = float(r["close"]) > recent_high
    bearish_bos = float(r["close"]) < recent_low
    if bullish_bos:
        score += 22; structure = "BOS ↑"
        reasons.append("Bullish break of structure")
    elif bearish_bos:
        score -= 22; structure = "BOS ↓"
        reasons.append("Bearish break of structure")
    else:
        prev_high = float(df.iloc[-6:-1]["high"].max())
        prev_low = float(df.iloc[-6:-1]["low"].min())
        if float(r["close"]) > prev_high:
            score += 10; structure = "MSS ↑"
            reasons.append("Short-term bullish structure shift")
        elif float(r["close"]) < prev_low:
            score -= 10; structure = "MSS ↓"
            reasons.append("Short-term bearish structure shift")
        else:
            structure = "RANGE"

    # Liquidity sweep: wick beyond a recent extreme, then close back inside.
    if float(r["high"]) > recent_high and float(r["close"]) < recent_high:
        score -= 18; liquidity = "BUY-SIDE SWEEP"
        reasons.append("Buy-side liquidity swept and rejected")
    elif float(r["low"]) < recent_low and float(r["close"]) > recent_low:
        score += 18; liquidity = "SELL-SIDE SWEEP"
        reasons.append("Sell-side liquidity swept and rejected")
    else:
        liquidity = "NONE"

    # Fair value gap heuristic using three consecutive candles.
    fvg = "NONE"
    if len(df) >= 3:
        a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        if float(c["low"]) > float(a["high"]):
            score += 12; fvg = "BULLISH FVG"; reasons.append("Bullish fair-value gap")
        elif float(c["high"]) < float(a["low"]):
            score -= 12; fvg = "BEARISH FVG"; reasons.append("Bearish fair-value gap")

    # Order-block heuristic: opposite candle before a displacement candle.
    order_block = "NONE"
    atr = float(r.get("atr", 0) or 0)
    if atr > 0 and len(df) >= 3:
        prev = df.iloc[-2]
        body = abs(float(r["close"]) - float(r["open"]))
        if body >= 1.15 * atr:
            if float(prev["close"]) < float(prev["open"]) and float(r["close"]) > float(r["open"]):
                score += 10; order_block = "BULLISH OB"; reasons.append("Bullish displacement from prior bearish candle")
            elif float(prev["close"]) > float(prev["open"]) and float(r["close"]) < float(r["open"]):
                score -= 10; order_block = "BEARISH OB"; reasons.append("Bearish displacement from prior bullish candle")

    # Premium/discount zone relative to the recent dealing range.
    rng = recent_high - recent_low
    pos = (float(r["close"]) - recent_low) / rng if rng > 0 else 0.5
    if pos <= 0.35:
        score += 6; zone = "DISCOUNT"
    elif pos >= 0.65:
        score -= 6; zone = "PREMIUM"
    else:
        zone = "EQUILIBRIUM"

    label = "BULLISH" if score >= 15 else "BEARISH" if score <= -15 else "MIXED"
    return {
        "score": _clamp(score),
        "label": label,
        "structure": structure,
        "liquidity": liquidity,
        "order_block": order_block,
        "fvg": fvg,
        "zone": zone,
        "reasons": reasons[:5],
    }


def advanced_snapshot(df: pd.DataFrame):
    enriched = enrich(df)
    if len(enriched) < 30:
        return df, technical_snapshot(df), smart_money_snapshot(df)
    return enriched, technical_snapshot(enriched), smart_money_snapshot(enriched)
