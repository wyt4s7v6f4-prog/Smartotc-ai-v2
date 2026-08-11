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
