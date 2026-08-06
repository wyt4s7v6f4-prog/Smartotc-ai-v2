from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.providers.twelvedata import get_forex_data
from app.providers.scanner import scan_market

from app.indicators.analysis import analyze

app = FastAPI()

templates = Jinja2Templates(directory="backend/app/templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


@app.get("/analyze")
def get_analysis(
    symbol: str = "BTCUSDT",
    interval: str = "1h"
):
    if "/" in symbol or "OTC" in symbol:
        symbol = symbol.replace(" OTC", "")
        return get_forex_data(symbol=symbol, interval=interval)

    return analyze(symbol, interval)


@app.get("/scan")
def market_scan(interval: str = "1h"):
    return scan_market(interval)