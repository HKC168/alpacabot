"""
tests/test_dashboard_data_layer.py
Dashboard 雲端資料層測試

測試目標：確保 Dashboard 在以下環境都能正常運作：
  1. Streamlit Cloud（有 st.secrets）
  2. 本地開發（有 account_config.json + env vars）
  3. 降級模式（API 失敗，改用快取報告）
  4. 完全無資料（顯示適當提示，不崩潰）

執行：pytest tests/test_dashboard_data_layer.py -v -m "not live"
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ─── 不直接 import data_layer，讓每個 test 可以獨立 mock st.secrets ─────────


def _import_data_layer():
    """延遲 import，確保 mock 先行設定"""
    import importlib
    import dashboard.data_layer as dl
    importlib.reload(dl)
    return dl


# ─── Mock Streamlit Secrets 的輔助 Fixture ────────────────────────────────────

FAKE_SECRETS = {
    "accounts": {"ids": ["TEST001", "TEST002"]},
    "TEST001": {
        "name":            "Test Account One",
        "api_key":         "TEST_KEY_001",
        "secret_key":      "TEST_SECRET_001",
        "endpoint":        "https://paper-api.alpaca.markets",
        "active_strategy": "top10_nasdaq_equal",
        "email":           "test1@test.com",
    },
    "TEST002": {
        "name":            "Test Account Two",
        "api_key":         "TEST_KEY_002",
        "secret_key":      "TEST_SECRET_002",
        "endpoint":        "https://paper-api.alpaca.markets",
        "active_strategy": "top10_nasdaq_equal",
        "email":           "test2@test.com",
    },
}

FAKE_ACCOUNT_CONFIG = {
    "accounts": [
        {
            "id":              "CONFIG001",
            "name":            "Config Account",
            "endpoint":        "https://paper-api.alpaca.markets",
            "api_key_env":     "ALPACA_KEY_CONFIG001",
            "secret_key_env":  "ALPACA_SECRET_CONFIG001",
            "active_strategy": "top10_nasdaq_equal",
            "email":           "config@test.com",
        }
    ]
}


@pytest.fixture
def mock_st_secrets():
    """模擬 Streamlit Secrets 已設定的環境"""
    with patch("dashboard.data_layer._get_streamlit_secrets", return_value=FAKE_SECRETS):
        yield FAKE_SECRETS


@pytest.fixture
def mock_st_no_secrets():
    """模擬 Streamlit Secrets 未設定的環境"""
    with patch("dashboard.data_layer._get_streamlit_secrets", return_value={}):
        yield


@pytest.fixture
def config_file(tmp_path):
    """建立暫存的 account_config.json"""
    config_dir = tmp_path / "accounts"
    config_dir.mkdir()
    config_path = config_dir / "account_config.json"
    config_path.write_text(json.dumps(FAKE_ACCOUNT_CONFIG))
    return tmp_path


@pytest.fixture
def mock_alpaca_client():
    """模擬 Alpaca 客戶端"""
    client = MagicMock()
    client.get_account_info.return_value = {
        "account_id": "TEST001", "status": "ACTIVE",
        "cash": 90000.0, "equity": 100000.0,
        "portfolio_value": 100000.0, "buying_power": 200000.0,
        "long_market_value": 10000.0, "short_market_value": 0.0,
        "currency": "USD",
    }
    client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10.0, "market_value": 2000.0,
         "avg_cost": 190.0, "current_price": 200.0,
         "unrealized_pl": 100.0, "unrealized_plpc": 0.05}
    ]
    client.get_orders_today.return_value = [
        {"order_id": "ORD1", "symbol": "AAPL", "side": "buy",
         "qty": 10.0, "status": "filled", "filled_qty": 10.0,
         "filled_avg_price": 190.0, "created_at": "2026-05-24T09:30:00Z"}
    ]
    return client


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 1：has_streamlit_secrets()
# ═══════════════════════════════════════════════════════════════════════════

class TestHasStreamlitSecrets:
    def test_returns_true_when_accounts_key_present(self, mock_st_secrets):
        from dashboard.data_layer import has_streamlit_secrets
        assert has_streamlit_secrets() is True

    def test_returns_false_when_no_secrets(self, mock_st_no_secrets):
        from dashboard.data_layer import has_streamlit_secrets
        assert has_streamlit_secrets() is False

    def test_returns_false_when_secrets_missing_accounts_key(self):
        """有 secrets 但缺少 accounts 區段"""
        with patch("dashboard.data_layer._get_streamlit_secrets",
                   return_value={"other_key": "value"}):
            from dashboard.data_layer import has_streamlit_secrets
            assert has_streamlit_secrets() is False


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 2：get_accounts_list()
# ═══════════════════════════════════════════════════════════════════════════

class TestGetAccountsList:
    def test_reads_from_streamlit_secrets(self, mock_st_secrets):
        """Secrets 存在時，從 Secrets 讀取帳戶列表"""
        from dashboard.data_layer import get_accounts_list
        ids = get_accounts_list()
        assert "TEST001" in ids
        assert "TEST002" in ids
        assert len(ids) == 2

    def test_falls_back_to_config_file(self, mock_st_no_secrets, config_file, monkeypatch):
        """Secrets 不存在時，從 account_config.json 讀取"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", config_file)
        from dashboard.data_layer import get_accounts_list
        ids = get_accounts_list()
        assert "CONFIG001" in ids

    def test_returns_empty_when_no_source(self, mock_st_no_secrets, tmp_path, monkeypatch):
        """Secrets 和 config 都不存在時回傳空列表，不崩潰"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", tmp_path)
        from dashboard.data_layer import get_accounts_list
        ids = get_accounts_list()
        assert ids == []

    def test_secrets_takes_priority_over_config(self, mock_st_secrets, config_file, monkeypatch):
        """Secrets 和 config 都存在時，優先使用 Secrets"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", config_file)
        from dashboard.data_layer import get_accounts_list
        ids = get_accounts_list()
        # Secrets 中的帳戶應在列表中
        assert "TEST001" in ids
        # config 中的帳戶不應覆蓋 Secrets
        assert "CONFIG001" not in ids


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 3：get_account_config()
# ═══════════════════════════════════════════════════════════════════════════

class TestGetAccountConfig:
    def test_reads_from_secrets(self, mock_st_secrets):
        """從 Secrets 讀取帳戶設定"""
        from dashboard.data_layer import get_account_config
        cfg = get_account_config("TEST001")
        assert cfg["api_key"]    == "TEST_KEY_001"
        assert cfg["secret_key"] == "TEST_SECRET_001"
        assert cfg["name"]       == "Test Account One"
        assert cfg["email"]      == "test1@test.com"

    def test_falls_back_to_config_and_env(self, mock_st_no_secrets, config_file, monkeypatch):
        """Secrets 不存在時，從 config + env vars 讀取"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", config_file)
        monkeypatch.setenv("ALPACA_KEY_CONFIG001",    "ENV_KEY_001")
        monkeypatch.setenv("ALPACA_SECRET_CONFIG001", "ENV_SECRET_001")
        from dashboard.data_layer import get_account_config
        cfg = get_account_config("CONFIG001")
        assert cfg["api_key"]    == "ENV_KEY_001"
        assert cfg["secret_key"] == "ENV_SECRET_001"

    def test_returns_empty_for_unknown_account(self, mock_st_secrets):
        """找不到帳戶時回傳空字典，不崩潰"""
        from dashboard.data_layer import get_account_config
        cfg = get_account_config("NONEXISTENT")
        assert cfg == {}

    def test_secrets_has_all_required_fields(self, mock_st_secrets):
        """設定應含所有必要欄位"""
        from dashboard.data_layer import get_account_config
        cfg = get_account_config("TEST001")
        required = {"name", "api_key", "secret_key", "endpoint", "active_strategy", "email"}
        assert required.issubset(cfg.keys())


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 4：build_alpaca_client()
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildAlpacaClient:
    def test_builds_client_from_secrets(self, mock_st_secrets):
        """從 Secrets 成功建立 AlpacaClient"""
        from dashboard.data_layer import build_alpaca_client
        with patch("src.alpaca_client.AlpacaClient") as MockClient:
            MockClient.return_value = MagicMock()
            client = build_alpaca_client("TEST001")
        MockClient.assert_called_once()

    def test_raises_for_missing_account(self, mock_st_no_secrets, tmp_path, monkeypatch):
        """找不到帳戶時拋出 ValueError"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", tmp_path)
        from dashboard.data_layer import build_alpaca_client
        with pytest.raises(ValueError, match="找不到帳戶設定"):
            build_alpaca_client("NONEXISTENT")

    def test_raises_for_empty_api_key(self, mock_st_secrets):
        """API Key 為空時拋出 ValueError"""
        secrets_no_key = {**FAKE_SECRETS}
        secrets_no_key["TEST001"] = {**FAKE_SECRETS["TEST001"], "api_key": ""}
        with patch("dashboard.data_layer._get_streamlit_secrets", return_value=secrets_no_key):
            from dashboard.data_layer import build_alpaca_client
            with pytest.raises(ValueError, match="缺少 API Key"):
                build_alpaca_client("TEST001")

    def test_injects_env_vars_for_alpaca_client(self, mock_st_secrets):
        """建立客戶端時應注入環境變數"""
        from dashboard.data_layer import build_alpaca_client
        with patch("src.alpaca_client.AlpacaClient"):
            build_alpaca_client("TEST001")
        assert os.environ.get("ALPACA_KEY_TEST001") == "TEST_KEY_001"
        assert os.environ.get("ALPACA_SECRET_TEST001") == "TEST_SECRET_001"


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 5：fetch_account_info() — Live + 降級
# ═══════════════════════════════════════════════════════════════════════════

class TestFetchAccountInfo:
    def test_returns_live_data_on_success(self, mock_st_secrets, mock_alpaca_client):
        """Alpaca API 正常時，回傳 live 資料"""
        with patch("dashboard.data_layer.build_alpaca_client", return_value=mock_alpaca_client):
            from dashboard.data_layer import fetch_account_info, DataSource
            result = fetch_account_info("TEST001")
        assert result.source == DataSource.LIVE
        assert result.data["cash"] == 90000.0
        assert result.data["equity"] == 100000.0

    def test_falls_back_to_report_on_api_failure(self, mock_st_secrets, tmp_path, monkeypatch):
        """API 失敗時，自動降級為快取報告"""
        # 建立假的報告檔案
        _setup_fake_report(tmp_path, "TEST001", cash=85000.0, equity=95000.0)
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR",         tmp_path)
        monkeypatch.setattr("src.report_generator.MODEL_DIR",        tmp_path / "reports" / "model")
        monkeypatch.setattr("src.report_generator.HISTORY_DIR",      tmp_path / "reports" / "history")
        monkeypatch.setattr("src.report_generator.NAV_DIR",          tmp_path / "reports" / "nav_history")

        with patch("dashboard.data_layer.build_alpaca_client",
                   side_effect=Exception("API 連線失敗")):
            from dashboard.data_layer import fetch_account_info, DataSource
            result = fetch_account_info("TEST001")

        assert result.source == DataSource.CACHED_REPORT
        assert result.data["cash"] == 85000.0

    def test_returns_unavailable_when_both_fail(self, mock_st_secrets, tmp_path, monkeypatch):
        """API 和報告都失敗時，回傳 unavailable（不崩潰）"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", tmp_path)
        with patch("dashboard.data_layer.build_alpaca_client",
                   side_effect=Exception("連線失敗")), \
             patch("dashboard.data_layer._load_latest_report_raw", return_value={}):
            from dashboard.data_layer import fetch_account_info, DataSource
            result = fetch_account_info("TEST001")
        assert result.source == DataSource.UNAVAILABLE
        assert result.data == {}


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 6：fetch_positions() — Live + 降級
# ═══════════════════════════════════════════════════════════════════════════

class TestFetchPositions:
    def test_returns_live_positions_on_success(self, mock_st_secrets, mock_alpaca_client):
        """Alpaca API 正常時，回傳即時持倉"""
        with patch("dashboard.data_layer.build_alpaca_client", return_value=mock_alpaca_client):
            from dashboard.data_layer import fetch_positions, DataSource
            result = fetch_positions("TEST001")
        assert result.source == DataSource.LIVE
        assert len(result.data) == 1
        assert result.data[0]["symbol"] == "AAPL"

    def test_falls_back_to_cached_holdings(self, mock_st_secrets):
        """API 失敗時，從報告的 holdings 降級"""
        cached_report = {"holdings": [{"symbol": "MSFT", "qty": 5.0}]}
        with patch("dashboard.data_layer.build_alpaca_client",
                   side_effect=Exception("失敗")), \
             patch("dashboard.data_layer._load_latest_report_raw",
                   return_value=cached_report):
            from dashboard.data_layer import fetch_positions, DataSource
            result = fetch_positions("TEST001")
        assert result.source == DataSource.CACHED_REPORT
        assert result.data[0]["symbol"] == "MSFT"

    def test_returns_empty_list_when_all_fail(self, mock_st_secrets):
        """所有來源都失敗時，回傳空列表（不崩潰）"""
        with patch("dashboard.data_layer.build_alpaca_client",
                   side_effect=Exception("失敗")), \
             patch("dashboard.data_layer._load_latest_report_raw", return_value={}):
            from dashboard.data_layer import fetch_positions, DataSource
            result = fetch_positions("TEST001")
        assert result.source == DataSource.UNAVAILABLE
        assert result.data == []


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 7：fetch_orders_today() — Live + 降級
# ═══════════════════════════════════════════════════════════════════════════

class TestFetchOrdersToday:
    def test_returns_live_orders_on_success(self, mock_st_secrets, mock_alpaca_client):
        """正常情況回傳即時委託"""
        with patch("dashboard.data_layer.build_alpaca_client", return_value=mock_alpaca_client):
            from dashboard.data_layer import fetch_orders_today, DataSource
            result = fetch_orders_today("TEST001")
        assert result.source == DataSource.LIVE
        assert result.data[0]["symbol"] == "AAPL"

    def test_falls_back_on_api_failure(self, mock_st_secrets):
        """API 失敗時從報告降級"""
        cached = {"orders_today": [{"symbol": "NVDA", "side": "buy"}]}
        with patch("dashboard.data_layer.build_alpaca_client", side_effect=Exception("失敗")), \
             patch("dashboard.data_layer._load_latest_report_raw", return_value=cached):
            from dashboard.data_layer import fetch_orders_today, DataSource
            result = fetch_orders_today("TEST001")
        assert result.source == DataSource.CACHED_REPORT
        assert result.data[0]["symbol"] == "NVDA"


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 8：get_latest_report()
# ═══════════════════════════════════════════════════════════════════════════

class TestGetLatestReport:
    def test_returns_report_when_exists(self, mock_st_secrets):
        """報告存在時正確回傳"""
        fake_report = {"report_date": "2026-05-24", "cash": 100000.0}
        with patch("dashboard.data_layer._load_latest_report_raw", return_value=fake_report):
            from dashboard.data_layer import get_latest_report, DataSource
            result = get_latest_report("TEST001")
        assert result.source == DataSource.CACHED_REPORT
        assert result.data["cash"] == 100000.0

    def test_returns_unavailable_when_no_report(self, mock_st_secrets):
        """無報告時回傳 unavailable，不崩潰"""
        with patch("dashboard.data_layer._load_latest_report_raw", return_value={}):
            from dashboard.data_layer import get_latest_report, DataSource
            result = get_latest_report("TEST001")
        assert result.source == DataSource.UNAVAILABLE
        assert result.data == {}


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 9：get_nav_history()
# ═══════════════════════════════════════════════════════════════════════════

class TestGetNavHistory:
    def test_returns_history_list(self, mock_st_secrets):
        """正常情況回傳歷史列表"""
        fake_hist = [
            {"date": "2026-05-22", "nav": 98000.0},
            {"date": "2026-05-23", "nav": 99000.0},
            {"date": "2026-05-24", "nav": 100000.0},
        ]
        with patch("dashboard.data_layer._import_nav_history", return_value=fake_hist,
                   create=True):
            pass  # 透過 mock src module 測試

        with patch("src.report_generator.get_nav_history", return_value=fake_hist):
            from dashboard.data_layer import get_nav_history
            hist = get_nav_history("TEST001")
        assert len(hist) == 3
        assert hist[-1]["nav"] == 100000.0

    def test_returns_empty_list_on_failure(self, mock_st_secrets, tmp_path, monkeypatch):
        """讀取失敗時回傳空列表，不崩潰"""
        monkeypatch.setattr("dashboard.data_layer.BASE_DIR", tmp_path)
        from dashboard.data_layer import get_nav_history
        hist = get_nav_history("NONEXISTENT")
        assert isinstance(hist, list)
        assert len(hist) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 10：DataResult
# ═══════════════════════════════════════════════════════════════════════════

class TestDataResult:
    def test_ok_is_true_for_live_source(self):
        from dashboard.data_layer import DataResult, DataSource
        r = DataResult(data={"x": 1}, source=DataSource.LIVE)
        assert r.ok is True
        assert r.is_live is True

    def test_ok_is_true_for_cached_report(self):
        from dashboard.data_layer import DataResult, DataSource
        r = DataResult(data={"x": 1}, source=DataSource.CACHED_REPORT)
        assert r.ok is True
        assert r.is_live is False

    def test_ok_is_false_for_unavailable(self):
        from dashboard.data_layer import DataResult, DataSource
        r = DataResult(data={}, source=DataSource.UNAVAILABLE)
        assert r.ok is False
        assert r.is_live is False

    def test_error_field_optional(self):
        from dashboard.data_layer import DataResult, DataSource
        r = DataResult(data={}, source=DataSource.LIVE)
        assert r.error is None

    def test_error_field_set(self):
        from dashboard.data_layer import DataResult, DataSource
        r = DataResult(data={}, source=DataSource.UNAVAILABLE, error="API 失敗")
        assert r.error == "API 失敗"


# ═══════════════════════════════════════════════════════════════════════════
# Test Group 11：get_full_dashboard_data()
# ═══════════════════════════════════════════════════════════════════════════

class TestGetFullDashboardData:
    def test_returns_all_required_keys(self, mock_st_secrets, mock_alpaca_client):
        """回傳所有必要的資料鍵"""
        with patch("dashboard.data_layer.build_alpaca_client", return_value=mock_alpaca_client), \
             patch("dashboard.data_layer._load_latest_report_raw", return_value={}), \
             patch("dashboard.data_layer.get_nav_history", return_value=[]):
            from dashboard.data_layer import get_full_dashboard_data
            result = get_full_dashboard_data("TEST001")

        required_keys = {"account_info", "positions", "orders",
                         "latest_report", "nav_history", "account_config"}
        assert required_keys.issubset(result.keys())

    def test_does_not_raise_on_api_failure(self, mock_st_secrets):
        """所有 API 都失敗時，不拋出例外，所有欄位都有值"""
        with patch("dashboard.data_layer.build_alpaca_client",
                   side_effect=Exception("全部失敗")), \
             patch("dashboard.data_layer._load_latest_report_raw", return_value={}), \
             patch("dashboard.data_layer.get_nav_history", return_value=[]):
            from dashboard.data_layer import get_full_dashboard_data
            result = get_full_dashboard_data("TEST001")

        assert "account_info" in result
        assert "positions"    in result
        assert "orders"       in result


# ─── 輔助函式 ─────────────────────────────────────────────────────────────────

def _setup_fake_report(tmp_path: Path, account_id: str,
                       cash: float = 100000.0, equity: float = 100000.0):
    """在 tmp_path 建立假的報告檔案"""
    from datetime import date
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    model_dir   = tmp_path / "reports" / "model"
    history_dir = tmp_path / "reports" / "history"
    nav_dir     = tmp_path / "reports" / "nav_history"
    for d in (model_dir, history_dir, nav_dir):
        d.mkdir(parents=True, exist_ok=True)

    report = {
        "report_date": date.today().isoformat(),
        "account_id":  account_id,
        "cash":        cash,
        "equity":      equity,
        "buying_power": equity * 2,
        "holdings":    [],
        "orders_today": [],
    }
    filename = f"{date.today().isoformat()}_{account_id}.json"
    for d in (model_dir, history_dir):
        (d / filename).write_text(json.dumps(report))
    return report
