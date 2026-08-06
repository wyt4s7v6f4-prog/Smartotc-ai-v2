from backend.app.indicators.analysis import analyze

CRYPTO_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "TRXUSDT",
]


def scan_market(interval="1h"):
    results = []

    for symbol in CRYPTO_PAIRS:
        try:
            data = analyze(symbol, interval)
            results.append(data)
        except Exception:
            continue

    results.sort(
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    return results[:5]