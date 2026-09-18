from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import aiohttp
import config

class BybitError(RuntimeError):
    pass

class BybitClient:
    def __init__(self):
        self.session = None

    @property
    def mode(self) -> str:
        return getattr(config, "TRADING_MODE", "PAPER").upper()

    @property
    def base_url(self) -> str:
        if self.mode == "DEMO":
            return config.BYBIT_DEMO_BASE_URL
        return config.BYBIT_BASE_URL

    @property
    def credentials(self):
        if self.mode == "DEMO":
            return config.BYBIT_DEMO_API_KEY, config.BYBIT_DEMO_API_SECRET
        return config.BYBIT_API_KEY, config.BYBIT_API_SECRET

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
        headers = {"Content-Type":"application/json","Accept":"application/json"}
        if private:
            api_key, api_secret = self.credentials
            if not api_key or not api_secret:
                raise BybitError(f"Bybit {self.mode} API credentials are not configured")
            timestamp = str(int(time.time()*1000))
            recv_window = str(config.BYBIT_RECV_WINDOW)
            raw = timestamp + api_key + recv_window + (query if method == "GET" else payload)
            signature = hmac.new(api_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
            headers.update({
                "X-BAPI-API-KEY": api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": recv_window,
                "X-BAPI-SIGN": signature,
                "X-BAPI-SIGN-TYPE": "2",
            })
        url = self.base_url.rstrip("/") + path
        async with self.session.request(method, url, params=params if method=="GET" else None,
                                         data=payload if method=="POST" else None, headers=headers) as response:
            raw_text = await response.text()
            try: data = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise BybitError(f"Bybit returned non-JSON response HTTP {response.status}: {raw_text[:300]}") from exc
            if response.status >= 400 or data.get("retCode") != 0:
                raise BybitError(f"Bybit error {data.get('retCode')}: {data.get('retMsg', response.status)}")
            return data["result"]

    async def klines(self,symbol,interval,limit=250):
        return (await self._request("GET","/v5/market/kline",{"category":"linear","symbol":symbol,"interval":interval,"limit":limit}))["list"]

    async def ticker(self,symbol):
        return (await self._request("GET","/v5/market/tickers",{"category":"linear","symbol":symbol}))["list"][0]

    async def orderbook(self,symbol,limit=25):
        return await self._request("GET","/v5/market/orderbook",{"category":"linear","symbol":symbol,"limit":limit})

    async def funding(self,symbol):
        return (await self._request("GET","/v5/market/funding/history",{"category":"linear","symbol":symbol,"limit":1})).get("list",[{}])[0]

    async def instrument(self,symbol):
        return (await self._request("GET","/v5/market/instruments-info",{"category":"linear","symbol":symbol}))["list"][0]

    async def balance(self):
        result = await self._request("GET","/v5/account/wallet-balance",{"accountType":"UNIFIED","coin":"USDT"},private=True)
        for coin in result.get("list",[{}])[0].get("coin",[]):
            if coin.get("coin")=="USDT":
                return float(coin.get("walletBalance",0))
        return 0.0

    async def position(self,symbol):
        result = await self._request("GET","/v5/position/list",{"category":"linear","symbol":symbol},private=True)
        for p in result.get("list",[]):
            if float(p.get("size",0))>0: return p
        return None

    async def set_leverage(self,symbol,leverage):
        try:
            await self._request("POST","/v5/position/set-leverage",body={"category":"linear","symbol":symbol,"buyLeverage":str(leverage),"sellLeverage":str(leverage)},private=True)
        except BybitError as exc:
            if "not modified" not in str(exc).lower(): raise

    async def create_postonly_order(self,symbol,side,qty,price,stop_loss,take_profit,order_link_id):
        return await self._request("POST","/v5/order/create",body={
            "category":"linear","symbol":symbol,"side":side,"orderType":"Limit","qty":qty,"price":price,
            "timeInForce":"PostOnly","positionIdx":0,"orderLinkId":order_link_id,
            "stopLoss":stop_loss,"takeProfit":take_profit,"slTriggerBy":"MarkPrice","tpTriggerBy":"MarkPrice"
        },private=True)

    async def order(self,symbol,order_id=None,order_link_id=None):
        result = await self._request("GET","/v5/order/realtime",{"category":"linear","symbol":symbol,"orderId":order_id,"orderLinkId":order_link_id,"openOnly":1},private=True)
        return (result.get("list") or [None])[0]

    async def order_history(self,symbol,order_id=None,order_link_id=None):
        result = await self._request("GET","/v5/order/history",{"category":"linear","symbol":symbol,"orderId":order_id,"orderLinkId":order_link_id,"limit":20},private=True)
        return (result.get("list") or [None])[0]

    async def cancel_order(self,symbol,order_id=None,order_link_id=None):
        if not order_id and not order_link_id: raise BybitError("cancel_order requires order_id or order_link_id")
        return await self._request("POST","/v5/order/cancel",body={"category":"linear","symbol":symbol,"orderId":order_id,"orderLinkId":order_link_id},private=True)

    async def closed_pnl(self, symbol):
        result = await self._request(
            "GET", "/v5/position/closed-pnl",
            {"category":"linear","symbol":symbol,"limit":1},
            private=True,
        )
        return result.get("list", [])

    async def close_market(self,symbol,position):
        side = "Sell" if position["side"]=="Buy" else "Buy"
        return await self._request("POST","/v5/order/create",body={"category":"linear","symbol":symbol,"side":side,"orderType":"Market","qty":position["size"],"reduceOnly":True,"positionIdx":0},private=True)
