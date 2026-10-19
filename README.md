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


## Free Render Web Service Telegram webhook
Telegram updates are handled by `POST /telegram/webhook` inside the existing FastAPI Web Service. No Background Worker is required.
Add these Environment Variables to the existing Render Web Service:
- `TELEGRAM_BOT_TOKEN`: token from @BotFather
- `PUBLIC_BASE_URL`: public HTTPS URL of this Render service, no trailing slash
- `TELEGRAM_WEBHOOK_SECRET`: random secret with letters, digits, `_` or `-`
The app registers the webhook on startup. Check `/telegram/status`.
Free Render services can spin down when idle, so first response after idle can be delayed. This does not connect verified Pocket Option OTC prices; live CALL/PUT remains disabled until a real provider and strategy are validated.
