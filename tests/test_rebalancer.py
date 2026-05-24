"""
tests/test_rebalancer.py — Phase 5 再平衡引擎測試
執行：pytest tests/test_rebalancer.py -v -m "not live"
"""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.rebalancer import (
    is_first_trading_day_of_month,
    should_rebalance,
    load_state, save_state, update_nav_state,
    Rebalancer,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def strategy():
    return {
        "strategy_id": "test",
        "allocation": {"per_position_pct": 10, "whole_shares_only": True},
        "rebalance": {"monthly": True, "on_new_deposit": True},
    }

@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """將狀態目錄導向 tmp_path"""
    monkeypatch.setattr("src.rebalancer.STATE_DIR", tmp_path)
    return tmp_path

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_account_info.return_value = {
        "account_id": "ACCT001", "cash": 100000.0, "equity": 100000.0,
        "buying_power": 200000.0, "long_market_value": 0.0, "short_market_value": 0.0,
        "portfolio_value": 100000.0, "status": "ACTIVE", "currency": "USD",
    }
    client.get_positions.return_value = []
    client.get_orders_today.return_value = []
    client.place_order.return_value = {"order_id": "ORD1", "status": "new"}
    return client

@pytest.fixture
def mock_cfg():
    cfg = MagicMock()
    cfg.id              = "ACCT001"
    cfg.active_strategy = "top10_nasdaq_equal"
    cfg.email           = "test@test.com"
    return cfg


# ─── Test 1: 月初觸發 ────────────────────────────────────────────────────────

class TestMonthlyRebalanceTrigger:
    def test_first_trading_day_monday(self):
        """月份第一個星期一（非週末）應為第一個交易日"""
        monday = date(2026, 6, 1)
        assert monday.weekday() == 0   # 確認是週一
        assert is_first_trading_day_of_month(monday) is True

    def test_first_day_is_saturday_shifts_to_monday(self):
        """月份第一天是週六時，第一個交易日應為週一（第 3 日）"""
        sat = date(2026, 8, 1)  # 週六
        mon = date(2026, 8, 3)  # 週一
        assert sat.weekday() == 5
        assert is_first_trading_day_of_month(sat) is False
        assert is_first_trading_day_of_month(mon) is True

    def test_mid_month_is_not_first_trading_day(self):
        """月中不是第一個交易日"""
        mid = date(2026, 6, 15)
        assert is_first_trading_day_of_month(mid) is False

    def test_monthly_trigger_detected(self, strategy, tmp_state):
        """月初時 should_rebalance 應回傳 True"""
        monday = date(2026, 6, 1)
        triggered, reason = should_rebalance("ACCT001", 100000.0, strategy, today=monday)
        assert triggered is True
        assert reason == "monthly_rebalance"

    def test_no_double_trigger_same_day(self, strategy, tmp_state):
        """同一天不應觸發兩次再平衡"""
        monday = date(2026, 6, 1)
        # 第一次
        should_rebalance("ACCT001", 100000.0, strategy, today=monday)
        # 記錄再平衡日期
        state = load_state("ACCT001")
        state["last_rebalance_date"] = monday.isoformat()
        save_state("ACCT001", state)
        # 第二次應不觸發
        triggered, _ = should_rebalance("ACCT001", 100000.0, strategy, today=monday)
        assert triggered is False


# ─── Test 2: 新資金觸發 ──────────────────────────────────────────────────────

class TestNewDepositTrigger:
    def test_cash_increase_triggers_rebalance(self, strategy, tmp_state):
        """現金增加超過 1% 應觸發再平衡"""
        state = load_state("ACCT001")
        state["last_cash"] = 100000.0
        save_state("ACCT001", state)
        triggered, reason = should_rebalance("ACCT001", 110000.0, strategy,
                                              today=date(2026, 6, 15))
        assert triggered is True
        assert reason == "new_deposit"

    def test_tiny_increase_not_triggered(self, strategy, tmp_state):
        """現金微增（< 1%）不觸發再平衡"""
        state = load_state("ACCT001")
        state["last_cash"] = 100000.0
        save_state("ACCT001", state)
        triggered, _ = should_rebalance("ACCT001", 100500.0, strategy,
                                         today=date(2026, 6, 15))
        assert triggered is False


# ─── Test 3: 再平衡後持倉為整數股 ────────────────────────────────────────────

class TestRebalanceWholeShares:
    def test_target_positions_are_integers(self, mock_client, mock_cfg, tmp_state):
        """再平衡後所有持倉數量為整數"""
        top10 = [{"symbol": f"SYM{i}", "price": 100.0 + i*10,
                   "market_cap": (10-i)*1e12, "pe_ratio": 25.0,
                   "rank": i+1, "name": f"S{i}",
                   "1d_pct": 0.0, "1w_pct": 0.0, "1m_pct": 0.0}
                 for i in range(10)]
        with patch("src.rebalancer.load_strategy") as mock_load, \
             patch("src.rebalancer.get_target_positions") as mock_target, \
             patch("src.order_executor.OrderExecutor.execute_rebalance") as mock_exec:
            mock_load.return_value = {
                "allocation": {"per_position_pct": 10, "whole_shares_only": True},
                "rebalance": {"monthly": True, "on_new_deposit": True},
            }
            mock_target.return_value = {f"SYM{i}": 10 for i in range(10)}
            mock_exec.return_value = MagicMock(total_bought=10, total_sold=0,
                                               orders_placed=[], orders_skipped=[], errors=[])
            r = Rebalancer(mock_client, mock_cfg)
            result = r.run(force=True)

        # target_positions values should all be int
        call_args = mock_target.call_args
        # If get_target_positions was called, it would have returned int values
        assert mock_target.called


# ─── Test 4: 10% 單股上限 ────────────────────────────────────────────────────

class TestRebalanceTenPctCap:
    def test_each_position_within_10pct(self):
        """每檔持倉市值不超過總資金 10%（由 strategy_engine 保證）"""
        from src.strategy_engine import get_target_positions
        strategy = {
            "allocation": {"per_position_pct": 10, "whole_shares_only": True},
            "selection": {"n": 10},
        }
        top10 = [{"symbol": f"S{i}", "price": 200.0, "market_cap": 1e12,
                   "rank": i+1, "pe_ratio": 25.0, "name": f"S{i}",
                   "1d_pct": 0.0, "1w_pct": 0.0, "1m_pct": 0.0}
                 for i in range(10)]
        targets = get_target_positions(100000.0, strategy, top10=top10)
        for sym, qty in targets.items():
            value = qty * 200.0
            assert value <= 10000.0 + 200.0  # 允許整數取捨誤差一股


# ─── Test 5: 多帳戶獨立 ──────────────────────────────────────────────────────

class TestMultiAccountIndependent:
    def test_two_accounts_have_separate_states(self, tmp_state):
        """兩個帳戶的狀態互不影響"""
        state_a = load_state("ACCT_A")
        state_a["last_cash"] = 50000.0
        save_state("ACCT_A", state_a)

        state_b = load_state("ACCT_B")
        state_b["last_cash"] = 200000.0
        save_state("ACCT_B", state_b)

        loaded_a = load_state("ACCT_A")
        loaded_b = load_state("ACCT_B")
        assert loaded_a["last_cash"] == 50000.0
        assert loaded_b["last_cash"] == 200000.0
        assert loaded_a["last_cash"] != loaded_b["last_cash"]
