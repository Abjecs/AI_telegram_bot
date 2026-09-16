from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import aiohttp

from config import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_BASE_URL, BYBIT_RECV_WINDOW


class BybitError(RuntimeError):
    pass


class BybitClient:
    def __init__(self) -> None:
        self.session = None

    async def start(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def _request(self, method, path, params=None, body=None, private=False):
        await self.start()
        params = params or {}
        body = body or {}
        query = urlencode([(k, v) for k, v in params.items() if v is not None])
        payload = json.dumps(body, separators=(",", ":")) if body else ""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        if private:
            if not BYBIT_API_KEY or not BYBIT_API_SECRET:
                raise BybitError("Bybit API credentials are not configured")
            timestamp = str(int(time.time() * 1000))
            recv_window = str(BYBIT_RECV_WINDOW)
            raw = timestamp + BYBIT_API_KEY + recv_window + (query if method == "GET" else payload)
            signature = hmac.new(
                BYBIT_API_SECRET.encode(), raw.encode(), hashlib.sha256
            ).hexdigest()
            headers.update(
                {
                    "X-BAPI-API-KEY": BYBIT_API_KEY,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": recv_window,
                    "X-BAPI-SIGN": signature,
                    "X-BAPI-SIGN-TYPE": "2",
                }
            )

        url = BYBIT_BASE_URL.rstrip("/") + path
        async with self.session.request(
            method,
            url,
            params=params if method == "GET" else None,
            data=payload if method == "POST" else None,
            headers=headers,
        ) as response:
            raw_text = await response.text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                preview = raw_text[:300].replace("\n", " ")
                raise BybitError(
                    f"Bybit returned non-JSON response HTTP {response.status}: {preview}"
                ) from exc

            if response.status >= 400 or data.get("retCode") != 0:
                raise BybitError(
                    f"Bybit error {data.get('retCode')}: {data.get('retMsg', response.status)}"
                )
            return data["result"]

    async def klines(self, symbol, interval, limit=250):
        return (
            await self._request(
                "GET",
                "/v5/market/kline",
                {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit},
            )
        )["list"]

    async def ticker(self, symbol):
        return (
            await self._request(
                "GET", "/v5/market/tickers", {"category": "linear", "symbol": symbol}
            )
        )["list"][0]

    async def orderbook(self, symbol, limit=25):
        return await self._request(
            "GET", "/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": limit}
        )

    async def funding(self, symbol):
        return (
            await self._request(
                "GET", "/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": 1}
            )
        ).get("list", [{}])[0]

    async def instrument(self, symbol):
        return (
            await self._request(
                "GET", "/v5/market/instruments-info", {"category": "linear", "symbol": symbol}
            )
        )["list"][0]

    async def balance(self):
        result = await self._request(
            "GET",
            "/v5/account/wallet-balance",
            {"accountType": "UNIFIED", "coin": "USDT"},
            private=True,
        )
        for coin in result.get("list", [{}])[0].get("coin", []):
            if coin.get("coin") == "USDT":
                return float(coin.get("walletBalance", 0))
        return 0.0

    async def position(self, symbol):
        result = await self._request(
            "GET",
            "/v5/position/list",
            {"category": "linear", "symbol": symbol},
            private=True,
        )
        for position in result.get("list", []):
            if float(position.get("size", 0)) > 0:
                return position
        return None

    async def set_leverage(self, symbol, leverage):
        try:
            await self._request(
                "POST",
                "/v5/position/set-leverage",
                body={
                    "category": "linear",
                    "symbol": symbol,
                    "buyLeverage": str(leverage),
                    "sellLeverage": str(leverage),
                },
                private=True,
            )
        except BybitError as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def create_market_order(self, symbol, side, qty, stop_loss, take_profit):
        return await self._request(
            "POST",
            "/v5/order/create",
            body={
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": qty,
                "positionIdx": 0,
                "timeInForce": "IOC",
                "stopLoss": stop_loss,
                "takeProfit": take_profit,
                "slTriggerBy": "MarkPrice",
                "tpTriggerBy": "MarkPrice",
            },
            private=True,
        )

    async def close_market(self, symbol, position):
        side = "Sell" if position["side"] == "Buy" else "Buy"
        return await self._request(
            "POST",
            "/v5/order/create",
            body={
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": position["size"],
                "reduceOnly": True,
                "positionIdx": 0,
            },
            private=True,
        )
