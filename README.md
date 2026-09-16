# AI Trading Bot — Bybit + Telegram + OpenAI

Telegram control bot for AI-assisted BTCUSDT perpetual day trading on Bybit.

## Architecture

`Bybit market data → indicators → multi-timeframe strategy → AI confirmation → risk manager → order`

The strategy is capital-independent: set `CAPITAL_USDT` to any positive amount, or `0` to use the live USDT wallet balance.

## Safety defaults

- `DRY_RUN=true` by default.
- Live trading requires both Bybit API credentials and `DRY_RUN=false`.
- Bybit API keys must not have withdrawal permission.
- Risk is calculated as a percentage of configured capital.
- Position size is capped by notional exposure and exchange minimums.
- Every live entry includes exchange-side stop-loss and take-profit parameters.
- The Telegram bot cannot switch live trading on.

## Strategy

- 5m execution timeframe.
- 15m trend confirmation.
- EMA 20/50/200.
- RSI 14.
- MACD.
- ATR-based stop and target.
- Volume ratio filter.
- 20-bar breakout context.
- Minimum signal score.
- AI confirmation only after technical filters pass.

## Environment

See `.env.example`.

For any account size, change only `CAPITAL_USDT` (or leave it at `0` to use the actual wallet balance). Risk is controlled by `RISK_PER_TRADE_PCT`.

## Telegram

- `/start` — overview
- `/status` — engine/account state
- `/trade` — latest technical signal
- `/paper` — safety information
- `/help` — commands

## Render

The service runs with `python bot_main.py` and listens on `PORT`.

A 24/7 trading process should run on an always-on Render plan. Do not rely on a sleeping/free instance for live trading.

## OpenAI

The bot uses the OpenAI API, not the ChatGPT consumer subscription. GPT-5.6 Luna is the default because it is the low-cost GPT-5.6 API model; API usage is billed separately.

## First launch

1. Keep `DRY_RUN=true`.
2. Add Telegram token.
3. Add OpenAI API key if AI confirmation is enabled.
4. Add Bybit API key/secret with Read + Trade and **without Withdraw**.
5. Deploy and inspect `/status` and Render logs.
6. Run paper mode long enough to collect a meaningful sample.
7. Only then set `DRY_RUN=false` if you explicitly want live orders.

This bot is an automated trading system, not a guarantee of profit. Backtest and paper-trade before risking funds.
