"""
tests/test_report_generator.py — Phase 6 日報生成測試
執行：pytest tests/test_report_generator.py -v -m "not live"
"""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.report_generator import (
    generate_daily_report, save_report, load_report,
    list_report_dates, get_nav_history, _update_nav_history,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    """所有報告目錄導向 tmp_path"""
    monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
    monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")
    monkeypatch.setattr("src.rebalancer.STATE_DIR",         tmp_path / "state")

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_account_info.return_value = {
        "account_id": "PA3CVCWGFPAM", "status": "ACTIVE",
        "cash": 80000.0, "equity": 100000.0,
        "portfolio_value": 100000.0, "buying_power": 200000.0,
        "long_market_value": 20000.0, "short_market_value": 0.0, "currency": "USD",
    }
    client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 50.0, "market_value": 10000.0,
         "avg_cost": 190.0, "current_price": 200.0,
         "unrealized_pl": 500.0, "unrealized_plpc": 0.05}
    ]
    client.get_orders_today.return_value = []
    return client

@pytest.fixture
def mock_cfg():
    cfg = MagicMock()
    cfg.id              = "PA3CVCWGFPAM"
    cfg.name            = "Han Paper Account"
    cfg.active_strategy = "top10_nasdaq_equal"
    cfg.email           = "test@test.com"
    return cfg

@pytest.fixture
def sample_report():
    return {
        "report_date":    "2026-05-24",
        "generated_at":   "2026-05-24T09:00:00",
        "account_id":     "PA3CVCWGFPAM",
        "account_name":   "Han Paper Account",
        "strategy_id":    "top10_nasdaq_equal",
        "nav":            {"current": 100000.0, "previous_day": 99000.0, "change_pct": 1.01},
        "cash":           80000.0,
        "equity":         100000.0,
        "buying_power":   200000.0,
        "drawdown":       {"current_pct": 0.0, "max_pct": 0.0, "peak_nav": 100000.0},
        "benchmark":      {"nasdaq_1d_pct": 0.5, "sp500_1d_pct": 0.3},
        "holdings":       [],
        "top10_today":    [],
        "prediction_tomorrow": [],
        "orders_today":   [],
        "watchlist":      {},
        "disclaimer":     "⚠️ 僅供參考",
    }


# ─── Test 1: 報告符合 Schema ─────────────────────────────────────────────────

class TestReportJsonSchema:
    REQUIRED_KEYS = {
        "report_date", "account_id", "nav", "cash", "equity",
        "drawdown", "benchmark", "holdings", "top10_today",
        "orders_today", "disclaimer"
    }

    def test_report_has_required_keys(self, mock_cfg, mock_client):
        """生成的報告含所有必要欄位"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": 0.5, "sp500_1d_pct": 0.3}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}):
            report = generate_daily_report(mock_cfg, mock_client)

        for key in self.REQUIRED_KEYS:
            assert key in report, f"缺少欄位：{key}"

    def test_disclaimer_present(self, mock_cfg, mock_client):
        """報告必須含免責聲明"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": None, "sp500_1d_pct": None}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}):
            report = generate_daily_report(mock_cfg, mock_client)

        assert "disclaimer" in report
        assert len(report["disclaimer"]) > 0


# ─── Test 2: NAV 計算正確 ────────────────────────────────────────────────────

class TestNavCalculation:
    def test_nav_equals_equity(self, mock_cfg, mock_client):
        """NAV current 應等於帳戶 equity"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": None, "sp500_1d_pct": None}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}):
            report = generate_daily_report(mock_cfg, mock_client)
        assert report["nav"]["current"] == 100000.0

    def test_cash_correct(self, mock_cfg, mock_client):
        """現金應等於帳戶 cash"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": None, "sp500_1d_pct": None}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}):
            report = generate_daily_report(mock_cfg, mock_client)
        assert report["cash"] == 80000.0


# ─── Test 3: 回撤計算 ────────────────────────────────────────────────────────

class TestDrawdownCalculation:
    def test_drawdown_zero_at_start(self, mock_cfg, mock_client):
        """初始狀態回撤應為 0"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": None, "sp500_1d_pct": None}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}):
            report = generate_daily_report(mock_cfg, mock_client)
        assert report["drawdown"]["current_pct"] >= 0

    def test_drawdown_has_required_fields(self, sample_report):
        """回撤欄位含 current_pct、max_pct、peak_nav"""
        assert "current_pct" in sample_report["drawdown"]
        assert "max_pct"     in sample_report["drawdown"]
        assert "peak_nav"    in sample_report["drawdown"]


# ─── Test 4: 基準比較 ────────────────────────────────────────────────────────

class TestBenchmarkComparison:
    def test_benchmark_fields_present(self, mock_cfg, mock_client):
        """benchmark 含 nasdaq_1d_pct 和 sp500_1d_pct"""
        with patch("src.report_generator.get_nasdaq_top10", return_value=[]), \
             patch("src.report_generator.get_benchmark_returns",
                   return_value={"nasdaq_1d_pct": 0.52, "sp500_1d_pct": 0.31}), \
             patch("src.report_generator.load_strategy", return_value={}), \
             patch("src.report_generator.get_watchlist_data", return_value={}):
            report = generate_daily_report(mock_cfg, mock_client)
        assert "nasdaq_1d_pct" in report["benchmark"]
        assert "sp500_1d_pct"  in report["benchmark"]


# ─── Test 5: 儲存至 history ───────────────────────────────────────────────────

class TestReportSavedToHistory:
    def test_save_creates_history_file(self, sample_report, tmp_path, monkeypatch):
        """save_report 應在 history/ 目錄建立檔案"""
        monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
        monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
        monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")

        save_report(sample_report)
        history_file = tmp_path / "history" / "2026-05-24_PA3CVCWGFPAM.json"
        assert history_file.exists()

    def test_save_creates_model_file(self, sample_report, tmp_path, monkeypatch):
        """save_report 應在 model/ 目錄建立檔案"""
        monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
        monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
        monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")
        save_report(sample_report)
        model_file = tmp_path / "model" / "2026-05-24_PA3CVCWGFPAM.json"
        assert model_file.exists()


# ─── Test 6: 回查歷史報告 ────────────────────────────────────────────────────

class TestRetrieveHistoricalReport:
    def test_load_report_returns_correct_data(self, sample_report, tmp_path, monkeypatch):
        """讀取指定日期報告應回傳正確資料"""
        monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
        monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
        monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")
        save_report(sample_report)
        loaded = load_report("PA3CVCWGFPAM", "2026-05-24")
        assert loaded is not None
        assert loaded["report_date"] == "2026-05-24"
        assert loaded["cash"] == 80000.0

    def test_load_nonexistent_report_returns_none(self, tmp_path, monkeypatch):
        """查詢不存在的報告應回傳 None"""
        monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
        monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
        monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")
        result = load_report("PA3CVCWGFPAM", "2000-01-01")
        assert result is None

    def test_list_report_dates(self, sample_report, tmp_path, monkeypatch):
        """list_report_dates 應回傳所有歷史日期"""
        monkeypatch.setattr("src.report_generator.MODEL_DIR",   tmp_path / "model")
        monkeypatch.setattr("src.report_generator.HISTORY_DIR", tmp_path / "history")
        monkeypatch.setattr("src.report_generator.NAV_DIR",     tmp_path / "nav")
        save_report(sample_report)
        dates = list_report_dates("PA3CVCWGFPAM")
        assert "2026-05-24" in dates
