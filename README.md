# Smartotc-ai-v2

## Auto signal mode
Select only the market. The engine automatically chooses the indicator feed and trade duration.

### Signal quality
AUTO mode does not force BUY/SELL when the setup is weak. A trade is issued only when the underlying rules produce BUY/SELL with an absolute score of at least 70 and calibrated historical probability of at least 70%. This reduces the number of trades and does not guarantee profit.

### Trade lifecycle
- Initial market selection can request a signal automatically.
- BUY/SELL starts immediately when a strong setup is available.
- The selected market determines the automatic expiry: OTC/FX 30s, crypto 60s.
- The current trade is monitored until expiry and then marked WIN/LOSS/DRAW from the available price feed.
- **No next trade is generated automatically after a result.** The button becomes **Next Signal** and the user must press it to request another signal.

OTC/FX uses the underlying FX feed as a proxy; broker-specific OTC prices can differ.


## Pocket Option Telegram bot (new scaffold)
- Backend adds `/pocket-option/status` and `/pocket-option/analyze`.
- `backend/bot.py` adds Telegram menu and requests analysis from the API.
- Set `TELEGRAM_BOT_TOKEN` and `API_BASE_URL` in Render.
- Deploy the existing web service from `backend/` using `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Add a Render Background Worker with root directory `backend`, build command `pip install -r requirements.txt`, start command `python bot.py`.
- The Pocket Option endpoint deliberately returns no CALL/PUT until a provider for the platform's own OTC quotes has been verified and integrated. Existing Quotex data and Twelve Data FX candles are not silently substituted for Pocket Option OTC.
- This scaffold does not yet implement Premium payments, database-backed history, or a real directional strategy.
