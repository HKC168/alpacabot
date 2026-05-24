"""
report_generator.py
日報生成模組（Phase 6）— Model/View 分離設計

- Report Model：標準 JSON 格式（reports/model/）
- 歷史報告：永久存檔（reports/history/）
- NAV 歷史：用於繪製走勢圖（reports/nav_history/）
- 客戶可回查任意日期的歷史報告

⚠️ 本模組產生的所有資料僅供資訊整理與研究參考，不構成投資建議。
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.alpaca_client import AlpacaClient, AccountConfig
from src.market_data import get_nasdaq_top10, get_benchmark_returns, get_multi_stock_info
from src.rebalancer import load_state, update_nav_state
from src.strategy_engine import load_strategy, get_watchlist_data

logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent.parent
MODEL_DIR   = BASE_DIR / "reports" / "model"
HISTORY_DIR = BASE_DIR / "reports" / "history"
NAV_DIR     = BASE_DIR / "reports" / "nav_history"


def _ensure_dirs():
    for d in (MODEL_DIR, HISTORY_DIR, NAV_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ─── 生成報告 ─────────────────────────────────────────────────────────────────

def generate_daily_report(account_cfg: AccountConfig, client: AlpacaClient) -> dict:
    """
    生成帳戶每日 JSON 報告

    包含：NAV、現金、回撤、持倉、Top10、關注清單、今日委託、基準比較

    ⚠️ 報告內容僅供資訊整理與研究參考，不構成投資建議。
    """
    _ensure_dirs()

    # ── 基本帳戶資料 ──────────────────────────────────────────────────────────
    account_info = client.get_account_info()
    positions    = client.get_positions()
    orders       = client.get_orders_today()
    nav          = account_info["equity"]
    cash         = account_info["cash"]

    # ── 狀態更新（NAV 歷史、回撤）────────────────────────────────────────────
    state = update_nav_state(account_cfg.id, nav, cash)
    prev_nav  = state.get("last_nav", nav) or nav
    change_pct = round((nav - prev_nav) / prev_nav * 100, 4) if prev_nav else 0.0
    peak_nav  = state.get("peak_nav", nav)
    drawdown  = round((peak_nav - nav) / peak_nav * 100, 4) if peak_nav > 0 else 0.0
    max_dd    = state.get("max_drawdown_pct", 0.0)

    # ── 市場資料 ──────────────────────────────────────────────────────────────
    benchmark = get_benchmark_returns()
    top10     = get_nasdaq_top10()

    # ── 策略與關注清單 ────────────────────────────────────────────────────────
    try:
        strategy  = load_strategy(account_cfg.active_strategy)
        watchlist = get_watchlist_data(strategy)
    except Exception as e:
        logger.warning("策略/關注清單載入失敗：%s", e)
        strategy  = {}
        watchlist = {}

    # ── 明日預測（依今日 Top10 作為明日預測；實際系統可接 ML 模型）─────────
    prediction = [
        {"rank": s["rank"], "symbol": s["symbol"], "reason": "市值持續居前10，保持觀察"}
        for s in top10[:10]
    ]

    report = {
        "report_date":    date.today().isoformat(),
        "generated_at":   datetime.now().isoformat(),
        "account_id":     account_cfg.id,
        "account_name":   account_cfg.name,
        "strategy_id":    account_cfg.active_strategy,
        "nav": {
            "current":      round(nav, 2),
            "previous_day": round(prev_nav, 2),
            "change_pct":   change_pct,
        },
        "cash":   round(cash, 2),
        "equity": round(account_info["equity"], 2),
        "buying_power":   round(account_info["buying_power"], 2),
        "drawdown": {
            "current_pct": drawdown,
            "max_pct":     round(max_dd, 4),
            "peak_nav":    round(peak_nav, 2),
        },
        "benchmark":         benchmark,
        "holdings":          positions,
        "top10_today":       top10,
        "prediction_tomorrow": prediction,
        "orders_today":      orders,
        "watchlist":         watchlist,
        "disclaimer":        "⚠️ 本報告所有內容僅供資訊整理與研究參考，不構成任何投資建議。",
    }

    # ── 更新 NAV 歷史 ─────────────────────────────────────────────────────────
    _update_nav_history(account_cfg.id, date.today().isoformat(), nav)

    return report


# ─── 儲存與讀取 ───────────────────────────────────────────────────────────────

def save_report(report: dict) -> Path:
    """
    儲存報告至 model/ 和 history/ 目錄

    model/：最新版本（每次覆寫）
    history/：依日期永久存檔
    """
    _ensure_dirs()
    account_id  = report["account_id"]
    report_date = report["report_date"]
    filename    = f"{report_date}_{account_id}.json"

    # 最新版
    model_path = MODEL_DIR / filename
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 歷史存檔
    history_path = HISTORY_DIR / filename
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("報告已儲存：%s", model_path)
    return model_path


def load_report(account_id: str, report_date: str) -> Optional[dict]:
    """
    讀取指定日期的報告

    report_date 格式：'YYYY-MM-DD'
    優先讀取 history/，不存在時嘗試 model/
    """
    _ensure_dirs()
    filename = f"{report_date}_{account_id}.json"
    for directory in (HISTORY_DIR, MODEL_DIR):
        path = directory / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    logger.warning("找不到報告：%s / %s", account_id, report_date)
    return None


def list_report_dates(account_id: str) -> list[str]:
    """列出帳戶所有歷史報告日期（由新到舊）"""
    _ensure_dirs()
    dates = set()
    for path in HISTORY_DIR.glob(f"*_{account_id}.json"):
        date_str = path.name.replace(f"_{account_id}.json", "")
        dates.add(date_str)
    return sorted(dates, reverse=True)


# ─── NAV 歷史 ─────────────────────────────────────────────────────────────────

def _nav_history_path(account_id: str) -> Path:
    _ensure_dirs()
    return NAV_DIR / f"{account_id}_nav.json"


def _update_nav_history(account_id: str, nav_date: str, nav: float) -> None:
    """新增或更新 NAV 歷史紀錄"""
    path = _nav_history_path(account_id)
    history: list[dict] = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            history = json.load(f)

    # 更新或新增
    existing = next((h for h in history if h["date"] == nav_date), None)
    if existing:
        existing["nav"] = round(nav, 2)
    else:
        history.append({"date": nav_date, "nav": round(nav, 2)})

    history.sort(key=lambda x: x["date"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def get_nav_history(account_id: str) -> list[dict]:
    """
    取得帳戶 NAV 歷史（供儀錶板繪圖用）

    回傳：[{"date": "2026-05-24", "nav": 100000.0}, ...]
    """
    path = _nav_history_path(account_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
