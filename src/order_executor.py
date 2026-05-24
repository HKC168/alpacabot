"""
order_executor.py
下單執行模組（Phase 4）

邏輯：
1. 比對目前持倉 vs 策略目標持倉
2. 計算 diff：需賣出哪些、需買進哪些
3. 先賣出（釋放現金），再買進
4. 防呆：重複下單檢查、現金不足跳過
5. 每筆成交立即發送通知

⚠️ 本模組僅執行使用者設定的策略，不構成投資建議。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.alpaca_client import AlpacaClient, AlpacaAPIError
from src.notifier import Notifier

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """單次執行結果摘要"""
    account_id:    str
    orders_placed: list[dict] = field(default_factory=list)
    orders_skipped: list[dict] = field(default_factory=list)
    errors:        list[str]  = field(default_factory=list)

    @property
    def total_bought(self) -> int:
        return sum(1 for o in self.orders_placed if o.get("side") == "buy")

    @property
    def total_sold(self) -> int:
        return sum(1 for o in self.orders_placed if o.get("side") == "sell")


class OrderExecutor:
    """
    負責計算 diff 並執行買賣委託

    使用方式：
        executor = OrderExecutor(client, notifier)
        result = executor.execute_rebalance(target_positions, current_positions, account_info)
    """

    def __init__(self, client: AlpacaClient, notifier: Notifier | None = None):
        self.client   = client
        self.notifier = notifier

    # ─── 公開方法 ────────────────────────────────────────────────────────────

    def execute_rebalance(
        self,
        target_positions: dict[str, int],
        current_positions: list[dict],
        account_info: dict,
    ) -> ExecutionResult:
        """
        依目標持倉執行再平衡

        參數：
            target_positions   {symbol: qty}（來自策略引擎）
            current_positions  Alpaca get_positions() 的回傳值
            account_info       Alpaca get_account_info() 的回傳值

        流程：先賣出，再買進
        """
        result = ExecutionResult(account_id=account_info.get("account_id", ""))

        current = {p["symbol"]: int(p["qty"]) for p in current_positions}
        to_sell, to_buy = self._calculate_diff(current, target_positions)

        open_orders = self._get_open_order_symbols()
        available_cash = account_info.get("cash", 0.0)

        # ── 賣出（先賣出釋放現金）────────────────────────────────────────────
        for symbol, qty in to_sell.items():
            if symbol in open_orders:
                msg = f"跳過賣出 {symbol}（已有未成交委託）"
                logger.warning(msg)
                result.orders_skipped.append({"symbol": symbol, "side": "sell", "reason": msg})
                continue
            order = self._place(symbol, qty, "sell", result)
            if order and self.notifier:
                self.notifier.notify_trade(symbol, "sell", qty, 0.0, order.get("order_id", ""))

        # ── 買進 ─────────────────────────────────────────────────────────────
        for symbol, qty in to_buy.items():
            if symbol in open_orders:
                msg = f"跳過買進 {symbol}（已有未成交委託）"
                logger.warning(msg)
                result.orders_skipped.append({"symbol": symbol, "side": "buy", "reason": msg})
                continue

            est_cost = qty * self._estimate_price(symbol)
            if est_cost > available_cash:
                msg = f"跳過買進 {symbol}（現金不足：需 ${est_cost:,.0f}，餘 ${available_cash:,.0f}）"
                logger.warning(msg)
                result.orders_skipped.append({"symbol": symbol, "side": "buy", "reason": msg})
                continue

            order = self._place(symbol, qty, "buy", result)
            if order:
                available_cash -= est_cost   # 保守估計扣除
                if self.notifier:
                    self.notifier.notify_trade(symbol, "buy", qty, 0.0, order.get("order_id", ""))

        logger.info("執行完成：買進 %d 筆，賣出 %d 筆，跳過 %d 筆",
                    result.total_bought, result.total_sold, len(result.orders_skipped))
        return result

    # ─── 計算差異 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _calculate_diff(
        current: dict[str, int],
        target: dict[str, int],
    ) -> tuple[dict[str, int], dict[str, int]]:
        """
        計算需賣出和需買進的股數

        回傳：(to_sell, to_buy)
        - to_sell：{symbol: qty_to_sell}（目前持有但目標不含，或目標數量更少）
        - to_buy ：{symbol: qty_to_buy}（目標有但目前不足）
        """
        to_sell: dict[str, int] = {}
        to_buy:  dict[str, int] = {}
        all_symbols = set(current) | set(target)

        for sym in all_symbols:
            curr = current.get(sym, 0)
            tgt  = target.get(sym, 0)
            diff = tgt - curr
            if diff > 0:
                to_buy[sym]  = diff
            elif diff < 0:
                to_sell[sym] = abs(diff)

        return to_sell, to_buy

    # ─── 內部輔助 ─────────────────────────────────────────────────────────────

    def _place(
        self,
        symbol: str,
        qty: int,
        side: str,
        result: ExecutionResult,
    ) -> dict | None:
        """送出單一委託，捕捉例外並記錄到 result"""
        try:
            order = self.client.place_order(symbol, qty, side)
            result.orders_placed.append({
                "symbol":   symbol,
                "side":     side,
                "qty":      qty,
                "order_id": order.get("order_id"),
                "status":   order.get("status"),
            })
            logger.info("委託送出：%s %s %d 股 → %s", side, symbol, qty, order.get("status"))
            return order
        except AlpacaAPIError as e:
            msg = f"{side} {symbol} 失敗：{e}"
            logger.error(msg)
            result.errors.append(msg)
            return None
        except ValueError as e:
            msg = f"{side} {symbol} 參數錯誤：{e}"
            logger.error(msg)
            result.errors.append(msg)
            return None

    def _get_open_order_symbols(self) -> set[str]:
        """取得目前有未成交委託的股票代號集合"""
        try:
            orders = self.client.get_orders_today()
            return {o["symbol"] for o in orders if o["status"] in ("new", "partially_filled", "accepted")}
        except Exception as e:
            logger.warning("取得委託列表失敗：%s", e)
            return set()

    def _estimate_price(self, symbol: str) -> float:
        """估算股價（用於現金不足檢查）；失敗時回傳保守高估值"""
        try:
            from src.market_data import get_stock_price
            price = get_stock_price(symbol)
            return price if price else 9999.0
        except Exception:
            return 9999.0
