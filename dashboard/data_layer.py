"""
dashboard/data_layer.py
雲端資料抽象層 — Dashboard 的所有資料都從這裡取得

設計原則：
1. 不依賴本地 .env 或環境變數（雲端部署時用 Streamlit Secrets）
2. 優先取得即時資料（Alpaca API），失敗時自動降級為歷史報告
3. 所有函式都不拋出例外（回傳空值並記錄 log）
4. 可在本地和 Streamlit Cloud 上無縫運行

資料優先順序：
  帳戶金鑰：Streamlit Secrets → account_config.json + env vars
  帳戶資料：Alpaca API（即時）→ 最新報告（快取）→ 空值
  市場資料：yfinance（雲端 API，永遠可用）
  歷史報告：reports/ 目錄（由 GitHub Actions commit，Streamlit Cloud 可讀）

⚠️ 本模組所有資料僅供資訊整理與研究參考，不構成投資建議。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent


# ─── 資料來源標籤 ─────────────────────────────────────────────────────────────

class DataSource:
    LIVE          = "live"           # 來自 Alpaca API 即時查詢
    CACHED_REPORT = "cached_report"  # 來自最新已存報告（GitHub Actions 產生）
    UNAVAILABLE   = "unavailable"    # 無法取得任何資料


@dataclass
class DataResult:
    """統一資料回傳格式（含資料來源標籤）"""
    data:   any
    source: str = DataSource.UNAVAILABLE
    error:  Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.source != DataSource.UNAVAILABLE

    @property
    def is_live(self) -> bool:
        return self.source == DataSource.LIVE


# ─── Streamlit Secrets 偵測 ───────────────────────────────────────────────────

def _get_streamlit_secrets() -> dict:
    """
    安全讀取 Streamlit Secrets，失敗時回傳空字典

    Streamlit Cloud 上：從 App Settings → Secrets 讀取
    本地開發：從 .streamlit/secrets.toml 讀取
    找不到時：回傳 {}
    """
    try:
        import streamlit as st
        # 使用 to_dict() 避免 AttrDict 的特殊行為
        return {k: dict(v) if hasattr(v, "items") else v
                for k, v in st.secrets.items()}
    except Exception:
        return {}


def has_streamlit_secrets() -> bool:
    """檢查 Streamlit Secrets 是否已設定（含 accounts 區段）"""
    secrets = _get_streamlit_secrets()
    return "accounts" in secrets and "ids" in secrets.get("accounts", {})


# ─── 帳戶設定 ─────────────────────────────────────────────────────────────────

def get_accounts_list() -> list[str]:
    """
    取得所有帳戶 ID 列表

    來源 1：Streamlit Secrets → [accounts] ids
    來源 2：accounts/account_config.json
    """
    # ── Streamlit Secrets ────────────────────────────────────────────────────
    secrets = _get_streamlit_secrets()
    if "accounts" in secrets:
        ids = secrets["accounts"].get("ids", [])
        if ids:
            logger.info("帳戶清單來自 Streamlit Secrets：%s", ids)
            return list(ids)

    # ── account_config.json（本地開發備援）──────────────────────────────────
    try:
        config_path = BASE_DIR / "accounts" / "account_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ids = [a["id"] for a in data.get("accounts", [])]
        logger.info("帳戶清單來自 account_config.json：%s", ids)
        return ids
    except Exception as e:
        logger.warning("account_config.json 讀取失敗：%s", e)

    return []


def get_account_config(account_id: str) -> dict:
    """
    取得單一帳戶設定（含 API Key）

    來源 1：Streamlit Secrets → [<account_id>] 區段
    來源 2：account_config.json + 環境變數

    回傳格式：
    {
        "name":            "Han Paper Account",
        "api_key":         "PKGIY...",
        "secret_key":      "AaKf...",
        "endpoint":        "https://paper-api.alpaca.markets",
        "active_strategy": "top10_nasdaq_equal",
        "email":           "gavin1.han@gmail.com",
    }
    """
    # ── Streamlit Secrets ────────────────────────────────────────────────────
    secrets = _get_streamlit_secrets()
    if account_id in secrets:
        cfg = secrets[account_id]
        if isinstance(cfg, dict) and cfg:
            logger.info("帳戶設定來自 Streamlit Secrets：%s", account_id)
            return dict(cfg)

    # ── account_config.json + 環境變數 ──────────────────────────────────────
    try:
        config_path = BASE_DIR / "accounts" / "account_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for a in data.get("accounts", []):
            if a["id"] == account_id:
                api_key    = os.environ.get(a["api_key_env"], "")
                secret_key = os.environ.get(a["secret_key_env"], "")
                if api_key and secret_key:
                    logger.info("帳戶設定來自 account_config.json + env：%s", account_id)
                    return {
                        "name":            a["name"],
                        "api_key":         api_key,
                        "secret_key":      secret_key,
                        "endpoint":        a["endpoint"],
                        "active_strategy": a["active_strategy"],
                        "email":           a["email"],
                    }
    except Exception as e:
        logger.warning("account_config.json 讀取失敗：%s", e)

    return {}


# ─── Alpaca 客戶端建立 ────────────────────────────────────────────────────────

def build_alpaca_client(account_id: str):
    """
    建立 AlpacaClient（使用 Secrets 中的金鑰，不需要本地 .env）

    回傳 AlpacaClient 或拋出 ValueError（找不到金鑰）
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from src.alpaca_client import AccountConfig, AlpacaClient

    cfg = get_account_config(account_id)
    if not cfg:
        raise ValueError(f"找不到帳戶設定：{account_id}")

    api_key    = cfg.get("api_key", "")
    secret_key = cfg.get("secret_key", "")
    if not api_key or not secret_key:
        raise ValueError(f"帳戶 {account_id} 缺少 API Key / Secret Key")

    # 注入環境變數（AlpacaClient 使用環境變數讀取金鑰）
    key_env    = f"ALPACA_KEY_{account_id}"
    secret_env = f"ALPACA_SECRET_{account_id}"
    os.environ[key_env]    = api_key
    os.environ[secret_env] = secret_key

    account_cfg = AccountConfig(
        id=account_id,
        name=cfg.get("name", account_id),
        endpoint=cfg.get("endpoint", "https://paper-api.alpaca.markets"),
        api_key_env=key_env,
        secret_key_env=secret_env,
        active_strategy=cfg.get("active_strategy", ""),
        email=cfg.get("email", ""),
    )
    return AlpacaClient(account_cfg)


# ─── 即時帳戶資料（Alpaca API）────────────────────────────────────────────────

def fetch_account_info(account_id: str) -> DataResult:
    """
    即時查詢帳戶資訊（現金、淨值、狀態）

    成功 → DataResult(data=dict, source="live")
    失敗 → DataResult(data=dict, source="cached_report")（從最新報告）
    完全失敗 → DataResult(data={}, source="unavailable")
    """
    # ── 嘗試 Alpaca API ──────────────────────────────────────────────────────
    try:
        client = build_alpaca_client(account_id)
        info   = client.get_account_info()
        return DataResult(data=info, source=DataSource.LIVE)
    except Exception as e:
        logger.warning("Alpaca 帳戶查詢失敗（%s）：%s，嘗試使用快取報告", account_id, e)

    # ── 降級：最新報告 ────────────────────────────────────────────────────────
    report = _load_latest_report_raw(account_id)
    if report:
        return DataResult(
            data={
                "cash":              report.get("cash", 0),
                "equity":            report.get("equity", 0),
                "buying_power":      report.get("buying_power", 0),
                "portfolio_value":   report.get("equity", 0),
                "long_market_value": sum(h.get("market_value", 0) for h in report.get("holdings", [])),
                "short_market_value": 0,
                "status":            "ACTIVE",
                "currency":          "USD",
            },
            source=DataSource.CACHED_REPORT,
            error=str(e) if 'e' in dir() else None,
        )

    return DataResult(data={}, source=DataSource.UNAVAILABLE,
                      error="API 失敗且無快取報告")


def fetch_positions(account_id: str) -> DataResult:
    """
    即時查詢持倉清單

    降級順序：Alpaca API → 最新報告的 holdings
    """
    try:
        client    = build_alpaca_client(account_id)
        positions = client.get_positions()
        return DataResult(data=positions, source=DataSource.LIVE)
    except Exception as e:
        logger.warning("持倉查詢失敗（%s）：%s", account_id, e)

    report = _load_latest_report_raw(account_id)
    if report:
        return DataResult(
            data=report.get("holdings", []),
            source=DataSource.CACHED_REPORT,
        )
    return DataResult(data=[], source=DataSource.UNAVAILABLE)


def fetch_orders_today(account_id: str) -> DataResult:
    """
    即時查詢今日委託

    降級順序：Alpaca API → 最新報告的 orders_today
    """
    try:
        client = build_alpaca_client(account_id)
        orders = client.get_orders_today()
        return DataResult(data=orders, source=DataSource.LIVE)
    except Exception as e:
        logger.warning("委託查詢失敗（%s）：%s", account_id, e)

    report = _load_latest_report_raw(account_id)
    if report:
        return DataResult(
            data=report.get("orders_today", []),
            source=DataSource.CACHED_REPORT,
        )
    return DataResult(data=[], source=DataSource.UNAVAILABLE)


# ─── 歷史報告（GitHub repo 檔案）─────────────────────────────────────────────

def _load_latest_report_raw(account_id: str) -> dict:
    """載入最新報告（內部使用，不拋例外）"""
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from src.report_generator import list_report_dates, load_report
        dates = list_report_dates(account_id)
        if not dates:
            return {}
        return load_report(account_id, dates[0]) or {}
    except Exception as e:
        logger.warning("報告讀取失敗：%s", e)
        return {}


def get_latest_report(account_id: str) -> DataResult:
    """
    取得最新日報 JSON（由 GitHub Actions 定期產生並 commit）

    在 Streamlit Cloud 上，GitHub Actions commit 的檔案可直接讀取。
    """
    report = _load_latest_report_raw(account_id)
    if report:
        return DataResult(data=report, source=DataSource.CACHED_REPORT)
    return DataResult(data={}, source=DataSource.UNAVAILABLE,
                      error="找不到報告檔案（請先執行 GitHub Actions）")


def get_report_by_date(account_id: str, report_date: str) -> DataResult:
    """取得指定日期的歷史報告"""
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from src.report_generator import load_report
        report = load_report(account_id, report_date)
        if report:
            return DataResult(data=report, source=DataSource.CACHED_REPORT)
    except Exception as e:
        logger.warning("歷史報告讀取失敗：%s", e)
    return DataResult(data={}, source=DataSource.UNAVAILABLE)


def get_available_report_dates(account_id: str) -> list[str]:
    """列出所有可查詢的歷史報告日期"""
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from src.report_generator import list_report_dates
        return list_report_dates(account_id)
    except Exception:
        return []


def get_nav_history(account_id: str) -> list[dict]:
    """
    取得 NAV 歷史（用於繪圖）

    [{"date": "2026-05-24", "nav": 100000.0}, ...]
    """
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from src.report_generator import get_nav_history as _get_nav
        return _get_nav(account_id)
    except Exception as e:
        logger.warning("NAV 歷史讀取失敗：%s", e)
        return []


# ─── 帳戶狀態摘要 ─────────────────────────────────────────────────────────────

def get_full_dashboard_data(account_id: str) -> dict:
    """
    一次性取得儀錶板所需的所有資料

    回傳格式：
    {
        "account_info":   DataResult,
        "positions":      DataResult,
        "orders":         DataResult,
        "latest_report":  DataResult,
        "nav_history":    list,
        "account_config": dict,
    }
    """
    return {
        "account_info":   fetch_account_info(account_id),
        "positions":      fetch_positions(account_id),
        "orders":         fetch_orders_today(account_id),
        "latest_report":  get_latest_report(account_id),
        "nav_history":    get_nav_history(account_id),
        "account_config": get_account_config(account_id),
    }
