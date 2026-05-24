"""
tests/test_alpaca_client.py
Phase 1 測試案例 — AlpacaClient 與多帳戶載入

測試分兩類：
1. Mock 測試：不需要真實 API，速度快，適合 CI
2. Live 測試：需要環境變數，測試真實 Alpaca Paper API

執行全部測試：  pytest tests/test_alpaca_client.py -v
執行 Mock 測試：pytest tests/test_alpaca_client.py -v -m "not live"
執行 Live 測試：pytest tests/test_alpaca_client.py -v -m live
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.alpaca_client import AccountConfig, AlpacaClient, AuthError, AlpacaAPIError
from src.account_loader import load_accounts, get_client, load_all_clients


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_account_cfg(monkeypatch):
    """建立測試用帳戶設定（使用假金鑰）"""
    monkeypatch.setenv("ALPACA_KEY_TEST123", "TEST_KEY")
    monkeypatch.setenv("ALPACA_SECRET_TEST123", "TEST_SECRET")
    return AccountConfig(
        id="TEST123",
        name="Test Account",
        endpoint="https://paper-api.alpaca.markets",
        api_key_env="ALPACA_KEY_TEST123",
        secret_key_env="ALPACA_SECRET_TEST123",
        active_strategy="top10_nasdaq_equal",
        email="test@test.com",
        notification={"trade_alert": True, "daily_report_time": "06:00"},
    )


@pytest.fixture
def client(sample_account_cfg):
    return AlpacaClient(sample_account_cfg)


@pytest.fixture
def sample_config_file():
    """建立暫存的 account_config.json 供測試使用"""
    config = {
        "accounts": [
            {
                "id": "ACCT001",
                "name": "Account One",
                "endpoint": "https://paper-api.alpaca.markets",
                "api_key_env": "ALPACA_KEY_ACCT001",
                "secret_key_env": "ALPACA_SECRET_ACCT001",
                "active_strategy": "top10_nasdaq_equal",
                "email": "user1@test.com",
                "notification": {"trade_alert": True, "daily_report_time": "06:00"},
            },
            {
                "id": "ACCT002",
                "name": "Account Two",
                "endpoint": "https://paper-api.alpaca.markets",
                "api_key_env": "ALPACA_KEY_ACCT002",
                "secret_key_env": "ALPACA_SECRET_ACCT002",
                "active_strategy": "momentum_weekly",
                "email": "user2@test.com",
                "notification": {"trade_alert": False, "daily_report_time": "06:00"},
            },
        ]
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config, f)
        return Path(f.name)


# ─── Test 1: 取得帳戶資訊 ───────────────────────────────────────────────────

class TestGetAccountInfo:
    def test_get_account_info_returns_correct_fields(self, client):
        """回傳含 cash、equity 等必要欄位"""
        mock_response = {
            "account_number": "TEST123",
            "status": "ACTIVE",
            "cash": "100000",
            "equity": "100000",
            "portfolio_value": "100000",
            "buying_power": "200000",
            "long_market_value": "0",
            "short_market_value": "0",
            "currency": "USD",
        }
        with patch.object(client, "_get", return_value=mock_response):
            info = client.get_account_info()

        assert info["cash"] == 100000.0
        assert info["equity"] == 100000.0
        assert info["status"] == "ACTIVE"
        assert info["currency"] == "USD"
        assert isinstance(info["buying_power"], float)

    def test_get_account_info_cash_is_float(self, client):
        """cash 欄位必須是 float"""
        mock_response = {"cash": "99999.50", "equity": "100000",
                         "portfolio_value": "100000", "buying_power": "200000",
                         "long_market_value": "0", "short_market_value": "0",
                         "account_number": "X", "status": "ACTIVE", "currency": "USD"}
        with patch.object(client, "_get", return_value=mock_response):
            info = client.get_account_info()
        assert isinstance(info["cash"], float)
        assert info["cash"] == 99999.50


# ─── Test 2: 多帳戶載入 ─────────────────────────────────────────────────────

class TestMultiAccountLoad:
    def test_load_accounts_returns_list(self, sample_config_file, monkeypatch):
        """正確載入多帳戶設定，回傳 list"""
        monkeypatch.setenv("ALPACA_KEY_ACCT001", "key1")
        monkeypatch.setenv("ALPACA_SECRET_ACCT001", "secret1")
        monkeypatch.setenv("ALPACA_KEY_ACCT002", "key2")
        monkeypatch.setenv("ALPACA_SECRET_ACCT002", "secret2")

        accounts = load_accounts(sample_config_file)
        assert len(accounts) == 2
        assert accounts[0].id == "ACCT001"
        assert accounts[1].id == "ACCT002"

    def test_load_accounts_correct_strategy(self, sample_config_file, monkeypatch):
        """每帳戶綁定正確的策略"""
        monkeypatch.setenv("ALPACA_KEY_ACCT001", "key1")
        monkeypatch.setenv("ALPACA_SECRET_ACCT001", "secret1")
        monkeypatch.setenv("ALPACA_KEY_ACCT002", "key2")
        monkeypatch.setenv("ALPACA_SECRET_ACCT002", "secret2")

        accounts = load_accounts(sample_config_file)
        assert accounts[0].active_strategy == "top10_nasdaq_equal"
        assert accounts[1].active_strategy == "momentum_weekly"

    def test_load_accounts_file_not_found(self):
        """設定檔不存在時拋出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            load_accounts(Path("/nonexistent/path/config.json"))

    def test_load_accounts_empty_accounts_raises(self):
        """accounts 為空時拋出 ValueError"""
        config = {"accounts": []}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(config, f)
            path = Path(f.name)
        with pytest.raises(ValueError, match="沒有任何帳戶設定"):
            load_accounts(path)


# ─── Test 3: 無效 Key 應拋出 AuthError ──────────────────────────────────────

class TestInvalidKeyRaises:
    def test_missing_api_key_env_raises_auth_error(self, monkeypatch):
        """環境變數未設定時，存取 api_key 應拋出 AuthError"""
        monkeypatch.delenv("ALPACA_KEY_NOKEY", raising=False)
        monkeypatch.setenv("ALPACA_SECRET_NOKEY", "some_secret")
        cfg = AccountConfig(
            id="NOKEY", name="No Key", endpoint="https://paper-api.alpaca.markets",
            api_key_env="ALPACA_KEY_NOKEY", secret_key_env="ALPACA_SECRET_NOKEY",
            active_strategy="test", email="x@x.com",
        )
        with pytest.raises(AuthError, match="ALPACA_KEY_NOKEY"):
            _ = cfg.api_key

    def test_401_response_raises_auth_error(self, client):
        """API 回傳 401 時應拋出 AuthError"""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.ok = False
        mock_resp.text = "Unauthorized"
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(AuthError):
                client.get_account_info()

    def test_403_response_raises_auth_error(self, client):
        """API 回傳 403 時應拋出 AuthError"""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.ok = False
        mock_resp.text = "Forbidden"
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(AuthError):
                client.get_account_info()


# ─── Test 4: 查詢持倉 ───────────────────────────────────────────────────────

class TestGetPositions:
    def test_get_positions_returns_list(self, client):
        """回傳持倉列表"""
        mock_data = [
            {
                "symbol": "AAPL",
                "qty": "10",
                "market_value": "1950.00",
                "avg_entry_price": "190.00",
                "current_price": "195.00",
                "unrealized_pl": "50.00",
                "unrealized_plpc": "0.0263",
            }
        ]
        with patch.object(client, "_get", return_value=mock_data):
            positions = client.get_positions()

        assert len(positions) == 1
        assert positions[0]["symbol"] == "AAPL"
        assert positions[0]["qty"] == 10.0
        assert positions[0]["current_price"] == 195.0

    def test_get_positions_empty(self, client):
        """無持倉時回傳空列表"""
        with patch.object(client, "_get", return_value=[]):
            positions = client.get_positions()
        assert positions == []

    def test_get_positions_multiple(self, client):
        """多筆持倉正確解析"""
        mock_data = [
            {"symbol": "AAPL", "qty": "10", "market_value": "1950",
             "avg_entry_price": "190", "current_price": "195",
             "unrealized_pl": "50", "unrealized_plpc": "0.026"},
            {"symbol": "MSFT", "qty": "5", "market_value": "2000",
             "avg_entry_price": "390", "current_price": "400",
             "unrealized_pl": "50", "unrealized_plpc": "0.025"},
        ]
        with patch.object(client, "_get", return_value=mock_data):
            positions = client.get_positions()
        assert len(positions) == 2
        symbols = [p["symbol"] for p in positions]
        assert "AAPL" in symbols
        assert "MSFT" in symbols


# ─── Test 5: 查詢今日委託 ───────────────────────────────────────────────────

class TestGetOrdersToday:
    def test_get_orders_today_returns_list(self, client):
        """回傳今日委託列表"""
        mock_data = [
            {
                "id": "order-001",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "10",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "195.00",
                "created_at": "2026-05-24T09:30:00Z",
            }
        ]
        with patch.object(client, "_get", return_value=mock_data):
            orders = client.get_orders_today()

        assert len(orders) == 1
        assert orders[0]["symbol"] == "AAPL"
        assert orders[0]["side"] == "buy"
        assert orders[0]["status"] == "filled"

    def test_get_orders_today_empty(self, client):
        """今日無委託時回傳空列表"""
        with patch.object(client, "_get", return_value=[]):
            orders = client.get_orders_today()
        assert orders == []

    def test_get_orders_buy_and_sell(self, client):
        """同時有買進和賣出委託"""
        mock_data = [
            {"id": "o1", "symbol": "AAPL", "side": "buy", "qty": "5",
             "status": "filled", "filled_qty": "5", "filled_avg_price": "195",
             "created_at": "2026-05-24T09:30:00Z"},
            {"id": "o2", "symbol": "MSFT", "side": "sell", "qty": "3",
             "status": "filled", "filled_qty": "3", "filled_avg_price": "400",
             "created_at": "2026-05-24T10:00:00Z"},
        ]
        with patch.object(client, "_get", return_value=mock_data):
            orders = client.get_orders_today()
        sides = [o["side"] for o in orders]
        assert "buy" in sides
        assert "sell" in sides


# ─── Live 測試（需要真實環境變數）────────────────────────────────────────────

@pytest.mark.live
class TestLiveAlpaca:
    """
    需要真實 API Key 才能執行
    執行：pytest tests/test_alpaca_client.py -v -m live
    """

    @pytest.fixture
    def live_client(self):
        cfg = AccountConfig(
            id="PA3CVCWGFPAM",
            name="Han Paper Account",
            endpoint="https://paper-api.alpaca.markets",
            api_key_env="ALPACA_KEY_PA3CVCWGFPAM",
            secret_key_env="ALPACA_SECRET_PA3CVCWGFPAM",
            active_strategy="top10_nasdaq_equal",
            email="gavin1.han@gmail.com",
        )
        return AlpacaClient(cfg)

    def test_live_get_account_info(self, live_client):
        info = live_client.get_account_info()
        assert info["status"] == "ACTIVE"
        assert info["cash"] > 0
        print(f"\n✅ 帳戶現金：${info['cash']:,.2f}")

    def test_live_get_positions(self, live_client):
        positions = live_client.get_positions()
        assert isinstance(positions, list)
        print(f"\n✅ 持倉數量：{len(positions)} 檔")

    def test_live_get_orders_today(self, live_client):
        orders = live_client.get_orders_today()
        assert isinstance(orders, list)
        print(f"\n✅ 今日委託：{len(orders)} 筆")
