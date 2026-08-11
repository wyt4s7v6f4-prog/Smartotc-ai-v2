# Quotex OTC feed

This version routes symbols ending in `OTC` to the authenticated Quotex WebSocket market-data adapter in `backend/app/providers/quotex_otc.py`.

## Render environment variable

Add:

- `QUOTEX_SSID` = your Quotex session SSID
- `QUOTEX_IS_DEMO` = `true` for demo or `false` for live market data
- optional `QUOTEX_REGION` if your Quotex account requires a specific region

The application does **not** use TwelveData as a fallback for OTC. If the Quotex feed is unavailable, the endpoint returns an explicit error instead of silently using a different price feed.

The adapter is data-only; it does not place trades.

The Quotex client is a community open-source client, not an official Quotex public API. See the repository documentation before using it in production.
