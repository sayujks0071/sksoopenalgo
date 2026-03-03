---
name: openalgo
description: Trade and query market data via OpenAlgo REST API (Indian brokers, 24+ supported). Use exec to call the API with curl.
version: "1.0.0"
author: OpenAlgo
---

# OpenAlgo Skill

When the user asks to **place orders**, **get quotes**, **check positions**, **view funds**, **search symbols**, or any **OpenAlgo** / **algo trading** request, use the **exec** tool to call the OpenAlgo REST API.

## Configuration

- **Base URL**: Use env `OPENALGO_BASE_URL` if set; otherwise `http://127.0.0.1:5000`. API path is `/api/v1/`.
- **API key**: Use env `OPENALGO_API_KEY`. Every request must include `"apikey": "<OPENALGO_API_KEY>"` in the JSON body (or header `X-API-KEY`).
- If the user has not set these, ask them to set `OPENALGO_API_KEY` (and optionally `OPENALGO_BASE_URL`) and ensure the OpenAlgo server is running.

## How to call the API

Use **exec** to run `curl`. Example pattern (replace ENDPOINT and add body):

```bash
curl -sS -X POST "$OPENALGO_BASE_URL/api/v1/ENDPOINT" \
  -H "Content-Type: application/json" \
  -d "{\"apikey\": \"$OPENALGO_API_KEY\", ...other fields...}"
```

If env vars are not in the shell, the user must provide the API key; you can then run curl with the key in the JSON body.

## Endpoints to use

| User intent | Endpoint | Method | Key body fields (always include apikey) |
|-------------|----------|--------|----------------------------------------|
| Place single order | placeorder | POST | symbol, exchange, action (BUY/SELL), quantity, product (MIS/CNC/NRML), pricetype (MARKET/LIMIT/SL/SL-M), optional price, trigger_price |
| Get quote / LTP | quotes | POST | symbol, exchange |
| Multiple quotes | multiquotes | POST | symbols (array), exchange |
| Open positions | positions | POST | (apikey only for full list) |
| Order book / order history | orderbook | POST | (apikey only) |
| Trade book / executions | tradebook | POST | (apikey only) |
| Account funds / margin | funds | POST | (apikey only) |
| Holdings (portfolio) | holdings | POST | (apikey only) |
| Search symbols | search | POST | searchtext, exchange |
| Option chain | optionchain | POST | symbol, exchange, expirydate, strikeprice |
| Historical OHLCV | history | POST | symbol, exchange, interval, fromdate, todate |
| Market depth (L5) | depth | POST | symbol, exchange |
| Cancel order | cancelorder | POST | orderid |
| Order status | orderstatus | POST | orderid |
| Ping / connection test | ping | POST | (apikey only) |

## Exchanges and formats

- **Exchanges**: NSE, BSE, NFO, BFO, MCX, CDS, etc.
- **Product**: MIS (intraday), CNC (delivery), NRML (F&O).
- **Symbol format**: Equity e.g. RELIANCE, SBIN; NSE index options e.g. NIFTY24JAN25000CE. Use the **search** endpoint if unsure.

## Response handling

- Responses are JSON: `{"status": "success", "data": {...}}` or `{"status": "error", "message": "..."}`. Summarize the result for the user; on error, report the message and suggest checking API key and OpenAlgo server.

## Safety

- Do not expose or log the user's API key. Use env vars in exec so the key does not appear in chat.
- For order placement, confirm quantity and symbol with the user when the request is ambiguous.
