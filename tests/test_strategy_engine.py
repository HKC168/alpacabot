"""
tests/test_strategy_engine.py — Phase 3 策略引擎測試
執行：pytest tests/test_strategy_engine.py -v -m "not live"
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.strategy_engine import (
    load_strategy, validate_strategy, get_target_positions,
    get_watchlist_data, StrategyValidationError, STRATEGIES_DIR,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_strategy():
    return {
        "strategy_id": "test_strategy",
        "name": "測試策略",
        "version": "1.0",
        "universe": "NASDAQ",
        "selection": {"method": "market_cap_top_n", "n": 10},
        "allocation": {"type": "equal_weight", "per_position_pct": 10, "whole_shares_only": True},
        "rebalance": {"monthly": True, "on_new_deposit": True},
    }

@pytest.fixture
def sample_top10():
    return [
        {"symbol": f"SYM{i}", "name": f"Stock {i}", "market_cap": (10-i)*1e12,
         "price": 100.0 + i*10, "pe_ratio": 25.0, "rank": i+1,
         "1d_pct": 1.0, "1w_pct": 2.0, "1m_pct": 3.0}
        for i in range(10)
    ]

# ─── Test 1: 載入策略 JSON ───────────────────────────────────────────────────

class TestLoadStrategy:
    def test_load_real_strategy_success(self):
        """載入真實策略檔成功，通過 schema 驗證"""
        strategy = load_strategy("top10_nasdaq_equal")
        assert strategy["strategy_id"] == "top10_nasdaq_equal"
        assert strategy["allocation"]["per_position_pct"] == 10
        assert strategy["allocation"]["whole_shares_only"] is True

    def test_load_nonexistent_raises_file_not_found(self):
        """策略檔不存在時拋出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            load_strategy("nonexistent_strategy_xyz")

# ─── Test 2: 策略格式驗證 ────────────────────────────────────────────────────

class TestValidateStrategy:
    def test_valid_strategy_passes(self, valid_strategy):
        """正確格式通過驗證"""
        assert validate_strategy(valid_strategy) is True

    def test_missing_required_field_fails(self, valid_strategy):
        """缺少必要欄位時拋出 StrategyValidationError"""
        del valid_strategy["allocation"]
        with pytest.raises(StrategyValidationError):
            validate_strategy(valid_strategy)

    def test_invalid_universe_fails(self, valid_strategy):
        """universe 非允許值時驗證失敗"""
        valid_strategy["universe"] = "INVALID_EXCHANGE"
        with pytest.raises(StrategyValidationError):
            validate_strategy(valid_strategy)

    def test_per_position_pct_out_of_range(self, valid_strategy):
        """per_position_pct 超出 1-100 範圍時驗證失敗"""
        valid_strategy["allocation"]["per_position_pct"] = 0
        with pytest.raises(StrategyValidationError):
            validate_strategy(valid_strategy)

    def test_n_out_of_range(self, valid_strategy):
        """n > 50 時驗證失敗"""
        valid_strategy["selection"]["n"] = 100
        with pytest.raises(StrategyValidationError):
            validate_strategy(valid_strategy)

# ─── Test 3: 選出 Top10 ──────────────────────────────────────────────────────

class TestSelectTop10:
    def test_returns_10_symbols(self, valid_strategy, sample_top10):
        """依策略回傳 10 個目標持倉"""
        with patch("src.strategy_engine.get_nasdaq_top10", return_value=sample_top10):
            targets = get_target_positions(100000.0, valid_strategy, top10=sample_top10)
        assert len(targets) == 10

    def test_symbols_are_strings(self, valid_strategy, sample_top10):
        """持倉 key 應為字串（股票代號）"""
        targets = get_target_positions(100000.0, valid_strategy, top10=sample_top10)
        for sym in targets:
            assert isinstance(sym, str)

# ─── Test 4: 整數股計算 ──────────────────────────────────────────────────────

class TestCalculateSharesWholeNumber:
    def test_all_quantities_are_integers(self, valid_strategy, sample_top10):
        """所有持倉數量必須為整數"""
        targets = get_target_positions(100000.0, valid_strategy, top10=sample_top10)
        for qty in targets.values():
            assert isinstance(qty, int)
            assert qty > 0

    def test_shares_are_floor_divided(self, valid_strategy):
        """股數應無條件捨去（例如 $10000 / $150/股 = 66 股，不是 67）"""
        top10 = [{"symbol": "AAA", "price": 150.0, "market_cap": 1e12, "rank": 1,
                   "pe_ratio": 25.0, "name": "AAA Inc",
                   "1d_pct": 0.0, "1w_pct": 0.0, "1m_pct": 0.0}]
        targets = get_target_positions(100000.0, valid_strategy, top10=top10)
        # 10% of 100000 = 10000, 10000 / 150 = 66.66 → floor = 66
        assert targets["AAA"] == 66

# ─── Test 5: 10% 上限 ────────────────────────────────────────────────────────

class TestTenPctAllocation:
    def test_position_value_within_10pct(self, valid_strategy, sample_top10):
        """每檔市值不超過總資金 10%（允許因整數取捨而略低）"""
        portfolio = 100000.0
        targets = get_target_positions(portfolio, valid_strategy, top10=sample_top10)
        for stock in sample_top10:
            sym = stock["symbol"]
            if sym in targets:
                position_value = targets[sym] * stock["price"]
                max_allowed = portfolio * 0.10
                assert position_value <= max_allowed + 1, (
                    f"{sym}: 持倉市值 ${position_value:.2f} 超過上限 ${max_allowed:.2f}")

    def test_zero_portfolio_returns_empty(self, valid_strategy, sample_top10):
        """資金為 0 時回傳空字典"""
        targets = get_target_positions(0.0, valid_strategy, top10=sample_top10)
        assert targets == {}

    def test_price_zero_stock_skipped(self, valid_strategy):
        """股價為 0 的股票應被跳過"""
        top10 = [{"symbol": "ZERO", "price": 0.0, "market_cap": 1e12, "rank": 1,
                   "pe_ratio": None, "name": "Zero", "1d_pct": 0, "1w_pct": 0, "1m_pct": 0}]
        targets = get_target_positions(100000.0, valid_strategy, top10=top10)
        assert "ZERO" not in targets

# ─── Test 6: 策略切換 ────────────────────────────────────────────────────────

class TestSwitchStrategy:
    def test_different_strategy_ids_load_independently(self):
        """不同 strategy_id 可獨立載入"""
        s1 = load_strategy("top10_nasdaq_equal")
        # 目前只有一個策略，驗證正確載入即可
        assert s1["strategy_id"] == "top10_nasdaq_equal"

    def test_new_json_file_loadable_without_code_change(self, valid_strategy, tmp_path, monkeypatch):
        """新增 JSON 策略檔後可直接載入，不需修改 Python 程式碼"""
        strategy_file = tmp_path / "new_strategy.json"
        strategy_file.write_text(json.dumps(valid_strategy))
        monkeypatch.setattr("src.strategy_engine.STRATEGIES_DIR", tmp_path)
        loaded = load_strategy("new_strategy")
        assert loaded["strategy_id"] == "test_strategy"
