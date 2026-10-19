"""Pocket Option OTC integration status.

Fail-closed by design: the existing project has a Quotex adapter and regular FX
proxy, but no verified Pocket Option OTC provider. Do not label FX proxy prices
as Pocket Option OTC prices.
"""
from datetime import datetime, timedelta, timezone

def analyze_pocket_option_otc(symbol: str, timeframe: str = "15s") -> dict:
    requested = datetime.now(timezone.utc)
    planned = requested + timedelta(seconds=5)
    return {
        "platform": "Pocket Option",
        "market": "OTC",
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "provider_unavailable",
        "direction": None,
        "score": None,
        "requested_at": requested.isoformat(),
        "planned_entry_at": planned.isoformat(),
        "entry_lead_seconds": 5,
        "live_signal": False,
        "message": (
            "Реальний сигнал не сформовано: у проєкті немає перевіреного "
            "джерела саме Pocket Option OTC-котирувань. Дані звичайного FX "
            "ринку або Quotex не можна підміняти ними."
        ),
    }
