"""
tests/test_order_executor.py — Phase 4 下單執行測試
執行：pytest tests/test_order_executor.py -v -m "not live"
"""

from unittest.mock import MagicMock, patch, call
import pytest

from src.order_executor import OrderExecutor, ExecutionResult
from src.alpaca_client import AlpacaAPIError


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_orders_today.return_value = []
    client.place_order.return_value = {"order_id": "ORD001", "status": "new", "side": "buy"}
    return client

@pytest.fixture
def executor(mock_client):
    return OrderExecutor(mock_client, notifier=None)

@pytest.fixture
def account_info():
    return {"account_id": "TEST", "cash": 100000.0, "equity": 100000.0}

@pytest.fixture
def current_positions():
    return [{"symbol": "AAPL", "qty": 5.0, "market_value": 975.0,
              "avg_cost": 190.0, "current_price": 195.0,
              "unrealized_pl": 25.0, "unrealized_plpc": 0.026}]


# ─── Test 1: 買單成功 ────────────────────────────────────────────────────────

class TestBuyOrderSuccess:
    def test_buy_order_placed_and_recorded(self, executor, mock_client, account_info):
        """有新股要買時，成功送出委託"""
        target = {"MSFT": 3}
        current_pos = []
        with patch.object(executor, "_estimate_price", return_value=100.0):
            result = executor.execute_rebalance(target, current_pos, account_info)
        mock_client.place_order.assert_called_once_with("MSFT", 3, "buy")
        assert result.total_bought == 1
        assert result.orders_placed[0]["symbol"] == "MSFT"
        assert result.orders_placed[0]["side"] == "buy"

    def test_buy_order_returns_order_id(self, executor, mock_client, account_info):
        """買單成功後有 order_id"""
        mock_client.place_order.return_value = {"order_id": "BUY-001", "status": "new"}
        target = {"AAPL": 10}
        with patch.object(executor, "_estimate_price", return_value=100.0):
            result = executor.execute_rebalance(target, [], account_info)
        assert result.orders_placed[0]["order_id"] == "BUY-001"


# ─── Test 2: 賣單成功 ────────────────────────────────────────────────────────

class TestSellOrderSuccess:
    def test_sell_order_placed_for_exited_stock(self, executor, mock_client, account_info, current_positions):
        """目標持倉不含某股時，應賣出"""
        target = {}   # 目標：清空
        mock_client.place_order.return_value = {"order_id": "SELL-001", "status": "new", "side": "sell"}
        result = executor.execute_rebalance(target, current_positions, account_info)
        mock_client.place_order.assert_called_once_with("AAPL", 5, "sell")
        assert result.total_sold == 1

    def test_sell_partial_when_target_qty_less(self, executor, mock_client, account_info):
        """目標持倉少於現有時，應只賣出差額"""
        current = [{"symbol": "AAPL", "qty": 10.0, "market_value": 1950.0,
                    "avg_cost": 190.0, "current_price": 195.0,
                    "unrealized_pl": 50.0, "unrealized_plpc": 0.026}]
        target = {"AAPL": 7}   # 目前 10 股，目標 7 股，賣 3 股
        mock_client.place_order.return_value = {"order_id": "X", "status": "new", "side": "sell"}
        result = executor.execute_rebalance(target, current, account_info)
        mock_client.place_order.assert_called_once_with("AAPL", 3, "sell")
        assert result.total_sold == 1


# ─── Test 3: 防止重複下單 ────────────────────────────────────────────────────

class TestNoDuplicateOrder:
    def test_skip_buy_if_open_order_exists(self, executor, mock_client, account_info):
        """已有未成交買單時不重複下單"""
        mock_client.get_orders_today.return_value = [
            {"symbol": "AAPL", "side": "buy", "status": "new",
             "qty": 10, "filled_qty": 0, "filled_avg_price": 0, "order_id": "X", "created_at": ""}
        ]
        target = {"AAPL": 10}
        result = executor.execute_rebalance(target, [], account_info)
        mock_client.place_order.assert_not_called()
        assert len(result.orders_skipped) == 1

    def test_skip_sell_if_open_order_exists(self, executor, mock_client, account_info, current_positions):
        """已有未成交賣單時不重複下單"""
        mock_client.get_orders_today.return_value = [
            {"symbol": "AAPL", "side": "sell", "status": "partially_filled",
             "qty": 5, "filled_qty": 2, "filled_avg_price": 195, "order_id": "Y", "created_at": ""}
        ]
        result = executor.execute_rebalance({}, current_positions, account_info)
        mock_client.place_order.assert_not_called()
        assert len(result.orders_skipped) == 1


# ─── Test 4: 現金不足跳過 ────────────────────────────────────────────────────

class TestInsufficientCashSkip:
    def test_skip_buy_when_insufficient_cash(self, executor, mock_client):
        """現金不足以買進時跳過，不送委託"""
        account = {"account_id": "TEST", "cash": 100.0, "equity": 100.0}
        target = {"TSLA": 10}   # 需要大量現金
        with patch.object(executor, "_estimate_price", return_value=500.0):
            result = executor.execute_rebalance(target, [], account)
        mock_client.place_order.assert_not_called()
        assert any("TSLA" in s.get("symbol", "") for s in result.orders_skipped)

    def test_sufficient_cash_buys_successfully(self, executor, mock_client, account_info):
        """現金充足時正常下單"""
        target = {"AAPL": 5}
        with patch.object(executor, "_estimate_price", return_value=100.0):
            result = executor.execute_rebalance(target, [], account_info)
        mock_client.place_order.assert_called_once()
        assert result.total_bought == 1


# ─── Test 5: 成交後觸發通知 ──────────────────────────────────────────────────

class TestTradeNotificationSent:
    def test_notifier_called_on_buy(self, mock_client, account_info):
        """買單成交後應呼叫 notifier.notify_trade"""
        notifier = MagicMock()
        executor = OrderExecutor(mock_client, notifier=notifier)
        target = {"AAPL": 5}
        with patch.object(executor, "_estimate_price", return_value=100.0):
            executor.execute_rebalance(target, [], account_info)
        notifier.notify_trade.assert_called_once()
        args = notifier.notify_trade.call_args[0]
        assert args[0] == "AAPL"
        assert args[1] == "buy"

    def test_notifier_called_on_sell(self, mock_client, account_info, current_positions):
        """賣單成交後應呼叫 notifier.notify_trade"""
        notifier = MagicMock()
        mock_client.place_order.return_value = {"order_id": "S1", "status": "new", "side": "sell"}
        executor = OrderExecutor(mock_client, notifier=notifier)
        executor.execute_rebalance({}, current_positions, account_info)
        notifier.notify_trade.assert_called_once()
        args = notifier.notify_trade.call_args[0]
        assert args[1] == "sell"

    def test_no_notifier_no_error(self, mock_client, account_info):
        """未設定 notifier 時不拋出錯誤"""
        executor = OrderExecutor(mock_client, notifier=None)
        target = {"AAPL": 5}
        with patch.object(executor, "_estimate_price", return_value=100.0):
            result = executor.execute_rebalance(target, [], account_info)
        assert result.total_bought == 1   # 正常執行


# ─── diff 計算單元測試 ────────────────────────────────────────────────────────

class TestCalculateDiff:
    def test_new_stock_to_buy(self):
        current = {}
        target  = {"AAPL": 10}
        to_sell, to_buy = OrderExecutor._calculate_diff(current, target)
        assert to_buy == {"AAPL": 10}
        assert to_sell == {}

    def test_exited_stock_to_sell(self):
        current = {"AAPL": 10}
        target  = {}
        to_sell, to_buy = OrderExecutor._calculate_diff(current, target)
        assert to_sell == {"AAPL": 10}
        assert to_buy  == {}

    def test_increase_qty(self):
        current = {"AAPL": 5}
        target  = {"AAPL": 8}
        to_sell, to_buy = OrderExecutor._calculate_diff(current, target)
        assert to_buy  == {"AAPL": 3}
        assert to_sell == {}

    def test_decrease_qty(self):
        current = {"AAPL": 10}
        target  = {"AAPL": 7}
        to_sell, to_buy = OrderExecutor._calculate_diff(current, target)
        assert to_sell == {"AAPL": 3}
        assert to_buy  == {}

    def test_no_change(self):
        current = {"AAPL": 5}
        target  = {"AAPL": 5}
        to_sell, to_buy = OrderExecutor._calculate_diff(current, target)
        assert to_sell == {}
        assert to_buy  == {}
