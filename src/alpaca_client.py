"""
alpaca_client.py
Alpaca API 封裝模組 — 支援多帳戶，金鑰全部從環境變數讀取

使用方式：
    from src.alpaca_client import AlpacaClient
    client = AlpacaClient(account_cfg)
    info = client.get_account_info()
"""

import os
import requests
from dataclasses import dataclass, field
from typing import Optional


class AuthError(Exception):
    """API 金鑰驗證失敗"""
    pass


class AlpacaAPIError(Exception):
    """Alpaca API 回傳錯誤"""
    pass


@dataclass
class AccountConfig:
    """單一帳戶設定"""
    id: str
    name: str
    endpoint: str
    api_key_env: str
    secret_key_env: str
    active_strategy: str
    email: str
    notification: dict = field(default_factory=dict)

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise AuthError(
                f"環境變數 {self.api_key_env} 未設定，請確認 .env 或 GitHub Secrets"
            )
        return key

    @property
    def secret_key(self) -> str:
        secret = os.environ.get(self.secret_key_env)
        if not secret:
            raise AuthError(
                f"環境變數 {self.secret_key_env} 未設定，請確認 .env 或 GitHub Secrets"
            )
        return secret


class AlpacaClient:
    """
    Alpaca REST API 客戶端（v2）

    提供：
    - get_account_info()    查詢帳戶資訊（現金、淨值等）
    - get_positions()       查詢目前持倉
    - get_orders_today()    查詢今日委託
    - place_order()         送出委託單
    - cancel_order()        取消委託
    """

    def __init__(self, account_cfg: AccountConfig):
        self.cfg = account_cfg
        self._base = account_cfg.endpoint.rstrip("/") + "/v2"
        self._headers = {
            "APCA-API-KEY-ID": account_cfg.api_key,
            "APCA-API-SECRET-KEY": account_cfg.secret_key,
            "accept": "application/json",
            "content-type": "application/json",
        }

    def _get(self, path: str, params: Optional[dict] = None) -> dict | list:
        url = f"{self._base}{path}"
        resp = requests.get(url, headers=self._headers, params=params, timeout=10)
        self._raise_for_status(resp)
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base}{path}"
        resp = requests.post(url, headers=self._headers, json=payload, timeout=10)
        self._raise_for_status(resp)
        return resp.json()

    def _delete(self, path: str) -> dict:
        url = f"{self._base}{path}"
        resp = requests.delete(url, headers=self._headers, timeout=10)
        self._raise_for_status(resp)
        return resp.json() if resp.text else {}

    @staticmethod
    def _raise_for_status(resp: requests.Response):
        if resp.status_code == 401:
            raise AuthError("API 金鑰無效或權限不足")
        if resp.status_code == 403:
            raise AuthError("帳戶無此操作權限（403 Forbidden）")
        if not resp.ok:
            raise AlpacaAPIError(
                f"Alpaca API 錯誤 {resp.status_code}: {resp.text[:200]}"
            )

    # ─── 帳戶資訊 ───────────────────────────────────────

    def get_account_info(self) -> dict:
        """
        查詢帳戶資訊

        回傳重要欄位：
        - cash              可用現金
        - equity            總淨值（現金 + 持倉市值）
        - portfolio_value   投資組合總值
        - buying_power      可用買入力道
        - status            帳戶狀態（ACTIVE / INACTIVE）
        """
        data = self._get("/account")
        return {
            "account_id": data.get("account_number"),
            "status": data.get("status"),
            "cash": float(data.get("cash", 0)),
            "equity": float(data.get("equity", 0)),
            "portfolio_value": float(data.get("portfolio_value", 0)),
            "buying_power": float(data.get("buying_power", 0)),
            "long_market_value": float(data.get("long_market_value", 0)),
            "short_market_value": float(data.get("short_market_value", 0)),
            "currency": data.get("currency", "USD"),
        }

    # ─── 持倉 ────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """
        查詢目前持倉清單

        每筆回傳欄位：
        - symbol        股票代號
        - qty           持有股數
        - market_value  目前市值（USD）
        - avg_cost      平均成本
        - unrealized_pl 未實現損益
        - unrealized_plpc 未實現損益百分比
        - current_price 目前股價
        """
        data = self._get("/positions")
        positions = []
        for p in data:
            positions.append({
                "symbol": p.get("symbol"),
                "qty": float(p.get("qty", 0)),
                "market_value": float(p.get("market_value", 0)),
                "avg_cost": float(p.get("avg_entry_price", 0)),
                "current_price": float(p.get("current_price", 0)),
                "unrealized_pl": float(p.get("unrealized_pl", 0)),
                "unrealized_plpc": float(p.get("unrealized_plpc", 0)),
            })
        return positions

    # ─── 委託單 ───────────────────────────────────────────

    def get_orders_today(self) -> list[dict]:
        """
        查詢今日所有委託單（含已成交、取消、待成交）

        每筆回傳欄位：
        - order_id  委託 ID
        - symbol    股票代號
        - side      buy / sell
        - qty       委託股數
        - status    委託狀態
        - filled_qty 已成交股數
        - filled_avg_price 成交均價
        - created_at 委託時間
        """
        data = self._get("/orders", params={"status": "all", "limit": 100})
        orders = []
        for o in data:
            orders.append({
                "order_id": o.get("id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "qty": float(o.get("qty") or 0),
                "status": o.get("status"),
                "filled_qty": float(o.get("filled_qty") or 0),
                "filled_avg_price": float(o.get("filled_avg_price") or 0),
                "created_at": o.get("created_at"),
            })
        return orders

    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        time_in_force: str = "day",
    ) -> dict:
        """
        送出委託單

        參數：
        - symbol        股票代號（e.g. "AAPL"）
        - qty           股數（整數）
        - side          "buy" 或 "sell"
        - order_type    "market"（預設）或 "limit"
        - time_in_force "day"（預設，收盤自動取消）

        回傳：order_id 及委託狀態
        """
        if qty <= 0:
            raise ValueError(f"委託股數必須 > 0，收到：{qty}")
        if side not in ("buy", "sell"):
            raise ValueError(f"side 必須是 buy 或 sell，收到：{side}")

        payload = {
            "symbol": symbol,
            "qty": str(int(qty)),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        data = self._post("/orders", payload)
        return {
            "order_id": data.get("id"),
            "symbol": data.get("symbol"),
            "side": data.get("side"),
            "qty": float(data.get("qty") or 0),
            "status": data.get("status"),
            "created_at": data.get("created_at"),
        }

    def cancel_order(self, order_id: str) -> dict:
        """取消指定委託單"""
        return self._delete(f"/orders/{order_id}")

    def cancel_all_orders(self) -> list:
        """取消所有未成交委託"""
        url = f"{self._base}/orders"
        resp = requests.delete(url, headers=self._headers, timeout=10)
        if resp.status_code == 207:
            return resp.json()
        self._raise_for_status(resp)
        return []
