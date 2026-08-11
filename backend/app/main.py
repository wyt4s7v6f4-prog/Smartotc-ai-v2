from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.providers.scanner import scan_market
from app.indicators.analysis import analyze

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
    interval: str = "1h"
):
    # Route ALL symbols through the unified analyzer. This is important for
    # OTC/Forex because the analyzer adds the same 10-second pre-entry timer
    # and uses the project's TwelveData FX proxy with rate-limit protection.
    return analyze(symbol, interval)


@app.get("/scan")
def market_scan(interval: str = "1h"):
    return scan_market(interval)
