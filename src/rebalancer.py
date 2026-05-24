"""
rebalancer.py
再平衡引擎（Phase 5）

觸發時機：
1. 每月初第一個交易日（工作日）
2. 偵測到新資金進入（現金增加 > 1%）

執行流程：
1. 載入策略 → 取得目標持倉
2. 呼叫 OrderExecutor 執行差額買賣

⚠️ 本模組僅依使用者設定的策略執行，不構成投資建議。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.alpaca_client import AlpacaClient, AccountConfig
from src.order_executor import OrderExecutor, ExecutionResult
from src.notifier import Notifier
from src.strategy_engine import load_strategy, get_target_positions

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent / "reports" / "state"


# ─── 狀態管理 ─────────────────────────────────────────────────────────────────

def _state_path(account_id: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{account_id}_state.json"


def load_state(account_id: str) -> dict:
    """載入帳戶狀態檔（不存在時回傳預設值）"""
    path = _state_path(account_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "account_id":          account_id,
        "last_cash":           0.0,
        "last_nav":            0.0,
        "peak_nav":            0.0,
        "max_drawdown_pct":    0.0,
        "last_rebalance_date": None,
    }


def save_state(account_id: str, state: dict) -> None:
    """儲存帳戶狀態"""
    path = _state_path(account_id)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def update_nav_state(account_id: str, nav: float, cash: float) -> dict:
    """更新 NAV、回撤峰值，回傳更新後的 state"""
    state = load_state(account_id)
    old_peak = state.get("peak_nav", 0.0) or 0.0
    peak_nav = max(old_peak, nav)
    drawdown = (peak_nav - nav) / peak_nav * 100 if peak_nav > 0 else 0.0
    max_dd   = max(state.get("max_drawdown_pct", 0.0), drawdown)

    state.update({
        "last_nav":         nav,
        "last_cash":        cash,
        "peak_nav":         peak_nav,
        "max_drawdown_pct": round(max_dd, 4),
    })
    save_state(account_id, state)
    return state


# ─── 觸發判斷 ─────────────────────────────────────────────────────────────────

def is_first_trading_day_of_month(today: date | None = None) -> bool:
    """
    判斷今天是否為本月第一個交易日（工作日）

    說明：交易日 = 週一到週五（此處不排除美國節假日，適合 Paper 帳戶）
    """
    if today is None:
        today = date.today()
    if today.day > 5:       # 第一個工作日最晚在第 5 日
        return False
    first = today.replace(day=1)
    while first.weekday() >= 5:   # 跳過週末
        first += timedelta(days=1)
    return today == first


def should_rebalance(
    account_id: str,
    current_cash: float,
    strategy: dict,
    today: date | None = None,
) -> tuple[bool, str]:
    """
    判斷是否需要再平衡

    回傳 (需要再平衡, 原因)
    原因字串：'monthly_rebalance' | 'new_deposit' | ''
    """
    state = load_state(account_id)

    # 1. 月初再平衡
    if strategy.get("rebalance", {}).get("monthly", False):
        if is_first_trading_day_of_month(today):
            last = state.get("last_rebalance_date")
            if last != (today or date.today()).isoformat():
                return True, "monthly_rebalance"

    # 2. 新資金偵測（現金增加超過 1%）
    if strategy.get("rebalance", {}).get("on_new_deposit", False):
        last_cash = state.get("last_cash", 0.0)
        if last_cash > 0 and current_cash > last_cash * 1.01:
            return True, "new_deposit"

    return False, ""


# ─── 主執行 ───────────────────────────────────────────────────────────────────

@dataclass
class RebalanceResult:
    account_id: str
    triggered:  bool
    reason:     str
    execution:  ExecutionResult | None = None


class Rebalancer:
    """再平衡引擎"""

    def __init__(self, client: AlpacaClient, account_cfg: AccountConfig):
        self.client  = client
        self.cfg     = account_cfg
        self.notifier = Notifier(account_cfg.email, account_cfg.id)

    def run(self, force: bool = False) -> RebalanceResult:
        """
        執行再平衡檢查與操作

        force=True 強制執行（忽略觸發條件，適合手動調用）
        """
        account_info = self.client.get_account_info()
        strategy     = load_strategy(self.cfg.active_strategy)

        triggered, reason = should_rebalance(
            self.cfg.id,
            account_info["cash"],
            strategy,
        )

        if not triggered and not force:
            logger.info("帳戶 %s：不需再平衡", self.cfg.id)
            return RebalanceResult(account_id=self.cfg.id, triggered=False, reason="")

        logger.info("帳戶 %s 觸發再平衡：%s", self.cfg.id, reason if not force else "force")

        positions = self.client.get_positions()
        target    = get_target_positions(account_info["equity"], strategy)

        executor  = OrderExecutor(self.client, self.notifier)
        execution = executor.execute_rebalance(target, positions, account_info)

        # 更新狀態
        state = load_state(self.cfg.id)
        state["last_rebalance_date"] = date.today().isoformat()
        state["last_cash"]           = account_info["cash"]
        state["last_nav"]            = account_info["equity"]
        if not state.get("peak_nav"):
            state["peak_nav"] = account_info["equity"]
        save_state(self.cfg.id, state)

        return RebalanceResult(
            account_id=self.cfg.id,
            triggered=True,
            reason=reason if not force else "force",
            execution=execution,
        )
