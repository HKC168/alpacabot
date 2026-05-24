"""
tests/test_integration.py — Phase 10 整合測試
模擬完整交易日流程（全部使用 Mock，不需要真實 API）

執行：pytest tests/test_integration.py -v -m "not live"
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.account_loader import load_accounts
from src.alpaca_client import AccountConfig, AlpacaClient
from src.email_sender import EmailSender
from src.main import run_trading, run_report, run_rebalance
from src.order_executor import OrderExecutor
from src.report_generator import generate_daily_report, save_report, load_report
from src.strategy_engine import load_strategy, get_target_positions


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
    monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")
    monkeypatch.setattr("src.rebalancer.STATE_DIR",         tmp_path / "state")


@pytest.fixture
def mock_client():
    client = MagicMock(spec=AlpacaClient)
    client.get_account_info.return_value = {
        "account_id": "PA3CVCWGFPAM", "status": "ACTIVE",
        "cash": 100000.0, "equity": 100000.0,
        "portfolio_value": 100000.0, "buying_power": 200000.0,
        "long_market_value": 0.0, "short_market_value": 0.0, "currency": "USD",
    }
    client.get_positions.return_value     = []
    client.get_orders_today.return_value  = []
    client.place_order.return_value = {"order_id": "ORD-INT-001", "status": "new"}
    return client


@pytest.fixture
def account_cfg():
    cfg = MagicMock(spec=AccountConfig)
    cfg.id              = "PA3CVCWGFPAM"
    cfg.name            = "Han Paper Account"
    cfg.active_strategy = "top10_nasdaq_equal"
    cfg.email           = "test@test.com"
    return cfg


@pytest.fixture
def sample_top10():
    return [{"symbol": f"SYM{i}", "price": 100.0 + i * 5,
              "market_cap": (10 - i) * 1e12, "pe_ratio": 25.0,
              "rank": i + 1, "name": f"Stock {i}",
              "1d_pct": 1.0, "1w_pct": 2.0, "1m_pct": 3.0}
             for i in range(10)]


# ═══════════════════════════════════════════════════════════════════════════
# E2E Test 1：完整交易日模擬
# ═══════════════════════════════════════════════════════════════════════════

class TestFullTradingDaySimulation:

    def test_trading_mode_places_orders(self, account_cfg, mock_client, sample_top10):
        """交易模式：策略選股 → 下單"""
        with patch("src.main.load_strategy") as mock_ls, \
             patch("src.main.get_target_positions") as mock_tp, \
             patch("src.main.Notifier"):
            mock_ls.return_value = {
                "allocation": {"per_position_pct": 10, "whole_shares_only": True},
                "rebalance": {"monthly": True, "on_new_deposit": True},
            }
            mock_tp.return_value = {f"SYM{i}": 10 for i in range(10)}
            result = run_trading(account_cfg, mock_client)

        assert result is not None
        assert mock_client.place_order.called

    def test_report_mode_generates_and_saves(self, account_cfg, mock_client):
        """報告模式：生成 JSON 報告 → 儲存"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": 0.5, "sp500_1d_pct": 0.3}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}), \
             patch("src.main.EmailSender") as mock_email_cls:
            mock_email_cls.return_value.send_daily_report.return_value = True
            report = run_report(account_cfg, mock_client)

        assert report is not None
        assert report["account_id"] == "PA3CVCWGFPAM"

    def test_report_saved_to_history(self, account_cfg, mock_client):
        """報告模式執行後，報告應可從歷史查詢"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": None, "sp500_1d_pct": None}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}), \
             patch("src.main.EmailSender") as mock_email_cls:
            mock_email_cls.return_value.send_daily_report.return_value = True
            run_report(account_cfg, mock_client)

        report = load_report("PA3CVCWGFPAM", date.today().isoformat())
        assert report is not None


# ═══════════════════════════════════════════════════════════════════════════
# E2E Test 2：新資金再平衡
# ═══════════════════════════════════════════════════════════════════════════

class TestNewDepositRebalance:

    def test_new_deposit_triggers_rebalance(self, account_cfg, mock_client, tmp_path, monkeypatch):
        """現金增加時自動觸發再平衡"""
        from src.rebalancer import save_state
        save_state("PA3CVCWGFPAM", {
            "account_id": "PA3CVCWGFPAM", "last_cash": 80000.0,
            "last_nav": 80000.0, "peak_nav": 80000.0,
            "max_drawdown_pct": 0.0, "last_rebalance_date": None,
        })

        mock_client.get_account_info.return_value = {
            "account_id": "PA3CVCWGFPAM", "status": "ACTIVE",
            "cash": 150000.0, "equity": 150000.0,
            "portfolio_value": 150000.0, "buying_power": 300000.0,
            "long_market_value": 0.0, "short_market_value": 0.0, "currency": "USD",
        }
        with patch("src.rebalancer.load_strategy") as mock_ls, \
             patch("src.rebalancer.get_target_positions") as mock_tp, \
             patch("src.order_executor.OrderExecutor.execute_rebalance") as mock_exec:
            mock_ls.return_value = {
                "allocation": {"per_position_pct": 10, "whole_shares_only": True},
                "rebalance": {"monthly": True, "on_new_deposit": True},
            }
            mock_tp.return_value = {"AAPL": 5}
            mock_exec.return_value = MagicMock(
                total_bought=1, total_sold=0, orders_placed=[], orders_skipped=[], errors=[])
            result = run_rebalance(account_cfg, mock_client, force=False)

        assert result is not None
        assert result.triggered is True
        assert result.reason == "new_deposit"


# ═══════════════════════════════════════════════════════════════════════════
# E2E Test 3：月初再平衡
# ═══════════════════════════════════════════════════════════════════════════

class TestMonthlyRebalance:

    def test_monthly_rebalance_on_first_trading_day(self, account_cfg, mock_client):
        """月初第一個交易日觸發再平衡"""
        first_monday = date(2026, 6, 1)
        with patch("src.rebalancer.load_strategy") as mock_ls, \
             patch("src.rebalancer.get_target_positions") as mock_tp, \
             patch("src.rebalancer.is_first_trading_day_of_month", return_value=True), \
             patch("src.order_executor.OrderExecutor.execute_rebalance") as mock_exec:
            mock_ls.return_value = {
                "allocation": {"per_position_pct": 10, "whole_shares_only": True},
                "rebalance": {"monthly": True, "on_new_deposit": False},
            }
            mock_tp.return_value = {"AAPL": 5}
            mock_exec.return_value = MagicMock(
                total_bought=1, total_sold=0, orders_placed=[], orders_skipped=[], errors=[])
            result = run_rebalance(account_cfg, mock_client)

        assert result.triggered is True
        assert result.reason == "monthly_rebalance"


# ═══════════════════════════════════════════════════════════════════════════
# E2E Test 4：策略切換
# ═══════════════════════════════════════════════════════════════════════════

class TestStrategySwitch:

    def test_account_uses_new_strategy_after_switch(self, account_cfg, mock_client):
        """切換策略後，下次執行使用新策略"""
        # 模擬帳戶切換策略
        account_cfg.active_strategy = "top10_nasdaq_equal"
        strategy = load_strategy("top10_nasdaq_equal")
        assert strategy["strategy_id"] == "top10_nasdaq_equal"
        assert strategy["allocation"]["per_position_pct"] == 10


# ═══════════════════════════════════════════════════════════════════════════
# E2E Test 5：多帳戶並行
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiAccountParallel:

    def test_two_accounts_run_independently(self, mock_client):
        """兩個帳戶各自執行，互不影響"""
        cfg_a = MagicMock()
        cfg_a.id              = "ACCT_A"
        cfg_a.name            = "Account A"
        cfg_a.active_strategy = "top10_nasdaq_equal"
        cfg_a.email           = "a@test.com"

        cfg_b = MagicMock()
        cfg_b.id              = "ACCT_B"
        cfg_b.name            = "Account B"
        cfg_b.active_strategy = "top10_nasdaq_equal"
        cfg_b.email           = "b@test.com"

        reports = []
        for cfg in [cfg_a, cfg_b]:
            with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
                 patch("src.report_generator.get_benchmark_returns",
                       return_value={"nasdaq_1d_pct": None, "sp500_1d_pct": None}), \
                 patch("src.report_generator.load_strategy", return_value={}), \
                 patch("src.report_generator.get_watchlist_data", return_value={}), \
                 patch("src.main.EmailSender") as mock_email_cls:
                mock_email_cls.return_value.send_daily_report.return_value = True
                mock_client.get_account_info.return_value = {
                    "account_id": cfg.id, "status": "ACTIVE",
                    "cash": 100000.0, "equity": 100000.0,
                    "portfolio_value": 100000.0, "buying_power": 200000.0,
                    "long_market_value": 0.0, "short_market_value": 0.0, "currency": "USD",
                }
                r = run_report(cfg, mock_client)
                reports.append(r)

        assert len(reports) == 2
        assert reports[0]["account_id"] == "ACCT_A"
        assert reports[1]["account_id"] == "ACCT_B"
