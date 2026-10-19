from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.providers.scanner import scan_market
from app.indicators.analysis import analyze
from app.providers.pocket_option import analyze_pocket_option_otc

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


@app.get("/analyze")
def get_analysis(
    symbol: str = "BTCUSDT",
    interval: str = "auto",
    mode: str = "auto"
):
    # Route ALL symbols through the unified analyzer. This is important for
    # OTC/Forex because the analyzer adds the same 10-second pre-entry timer
    # and uses the authenticated Quotex feed for OTC symbols.
    return analyze(symbol, interval, mode=mode)


@app.get("/scan")
def market_scan(interval: str = "1h"):
    return scan_market(interval)


@app.get("/pocket-option/status")
def pocket_option_status():
    return {
        "platform": "Pocket Option",
        "market": "OTC",
        "provider_configured": False,
        "live_signals_enabled": False,
        "message": "Pocket Option OTC feed is not yet verified or connected."
    }


@app.get("/pocket-option/analyze")
def pocket_option_analyze(
    symbol: str = "EUR/USD OTC",
    timeframe: str = "15s"
):
    # Signal request is intentionally fail-closed until a verified provider
    # for Pocket Option's own OTC quotes has been integrated.
    return analyze_pocket_option_otc(symbol, timeframe)
