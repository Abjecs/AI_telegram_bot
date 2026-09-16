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
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None, private: bool = False) -> dict:
        await self.start()
        params = params or {}
        body = body or {}
        query = urlencode([(k, v) for k, v in params.items() if v is not None])
        payload = json.dumps(body, separators=(",", ":")) if body else ""
        headers = {"Content-Type": "application/json"}
        if private:
            if not BYBIT_API_KEY or not BYBIT_API_SECRET:
                raise BybitError("Bybit API credentials are not configured")
            ts = str(int(time.time() * 1000))
            recv = str(BYBIT_RECV_WINDOW)
            sign_payload = ts + BYBIT_API_KEY + recv + (query if method == "GET" else payload)
            signature = hmac.new(BYBIT_API_SECRET.encode(), sign_payload.encode(), hashlib.sha256).hexdigest()
            headers.update({
                "X-BAPI-API-KEY": BYBIT_API_KEY,
                "X-BAPI-TIMESTAMP": ts,
                "X-BAPI-RECV-WINDOW": recv,
                "X-BAPI-SIGN": signature,
                "X-BAPI-SIGN-TYPE": "2",
            })
        url = BYBIT_BASE_URL.rstrip("/") + path
        async with self.session.request(method, url, params=params if method == "GET" else None, data=payload if method == "POST" else None, headers=headers) as r:
            data = await r.json(content_type=None)
            if r.status >= 400 or data.get("retCode") != 0:
                raise BybitError(f"Bybit error {data.get('retCode')}: {data.get('retMsg', r.status)}")
            return data["result"]

    async def klines(self, symbol: str, interval: str, limit: int = 250) -> list[list[str]]:
        result = await self._request("GET", "/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit})
        return result["list"]

    async def ticker(self, symbol: str) -> dict:
        result = await self._request("GET", "/v5/market/tickers", {"category": "linear", "symbol": symbol})
        return result["list"][0]

    async def instrument(self, symbol: str) -> dict:
        result = await self._request("GET", "/v5/market/instruments-info", {"category": "linear", "symbol": symbol})
        return result["list"][0]

    async def balance(self) -> float:
        result = await self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED", "coin": "USDT"}, private=True)
        coins = result.get("list", [{}])[0].get("coin", [])
        for coin in coins:
            if coin.get("coin") == "USDT":
                return float(coin.get("walletBalance", 0))
        return 0.0

    async def position(self, symbol: str) -> dict | None:
        result = await self._request("GET", "/v5/position/list", {"category": "linear", "symbol": symbol}, private=True)
        for p in result.get("list", []):
            if float(p.get("size", 0)) > 0:
                return p
        return None

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            await self._request("POST", "/v5/position/set-leverage", body={"category": "linear", "symbol": symbol, "buyLeverage": str(leverage), "sellLeverage": str(leverage)}, private=True)
        except BybitError as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def create_market_order(self, symbol: str, side: str, qty: str, stop_loss: str, take_profit: str) -> dict:
        body = {
            "category": "linear", "symbol": symbol, "side": side, "orderType": "Market",
            "qty": qty, "positionIdx": 0, "timeInForce": "IOC",
            "stopLoss": stop_loss, "takeProfit": take_profit,
            "slTriggerBy": "MarkPrice", "tpTriggerBy": "MarkPrice",
        }
        return await self._request("POST", "/v5/order/create", body=body, private=True)

    async def close_market(self, symbol: str, position: dict) -> dict:
        side = "Sell" if position["side"] == "Buy" else "Buy"
        return await self._request("POST", "/v5/order/create", body={
            "category": "linear", "symbol": symbol, "side": side, "orderType": "Market",
            "qty": position["size"], "reduceOnly": True, "positionIdx": 0,
        }, private=True)
