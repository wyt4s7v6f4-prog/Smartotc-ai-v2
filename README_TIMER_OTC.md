# SmartOTC AI — Timer + OTC update

This update adds:
- 10-second pre-entry countdown before the next candle.
- automatic `ENTRY NOW` confirmation after the countdown.
- OTC/Forex routing through the project's existing TwelveData provider.
- OTC badge in the interface.
- mobile-friendly layout for iPhone.
- explicit trade duration (30s, 1m, 5m, etc.) shown with each signal.
- automatic trade lifecycle: ENTRY IN → ENTRY NOW → trade countdown → RESULT.
- automatic WIN/LOSS/DRAW result based on entry vs expiry price.
- OTC results are calculated from the latest available FX proxy price.

Important: OTC quotes are broker-specific. The OTC selector uses the underlying FX feed as a proxy, so the exact broker OTC price can differ.

Replace the existing:
- `backend/app/indicators/analysis.py`
- `backend/app/templates/index.html`

Then commit/push to GitHub and let Render deploy.
