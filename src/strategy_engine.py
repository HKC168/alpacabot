"""
strategy_engine.py
策略引擎（Phase 3）— JSON 驅動，新增策略只需新增 JSON 檔

功能：
- 載入並驗證策略 JSON
- 依策略選出目標股票
- 計算各股目標持倉數量（整數股，不超過 per_position_pct）
- 新增策略：只需在 strategies/ 資料夾新增 JSON，不需修改 Python 程式碼

⚠️ 本模組輸出僅供資訊整理與研究參考，不構成投資建議。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import jsonschema

from src.market_data import get_nasdaq_top10, get_stock_price, get_multi_stock_info

logger = logging.getLogger(__name__)

STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"
SCHEMA_PATH    = STRATEGIES_DIR / "schema.json"


class StrategyValidationError(Exception):
    """策略 JSON 格式驗證失敗"""
    pass


# ─── 載入與驗證 ───────────────────────────────────────────────────────────────

def load_strategy(strategy_id: str) -> dict:
    """
    依 strategy_id 載入對應的 JSON 策略檔並驗證格式

    策略檔路徑：strategies/<strategy_id>.json
    """
    path = STRATEGIES_DIR / f"{strategy_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"策略檔不存在：{path}")

    with open(path, "r", encoding="utf-8") as f:
        strategy = json.load(f)

    validate_strategy(strategy)
    logger.info("策略載入成功：%s v%s", strategy["name"], strategy["version"])
    return strategy


def validate_strategy(strategy: dict) -> bool:
    """
    依 schema.json 驗證策略格式

    回傳 True 表示通過，否則拋出 StrategyValidationError
    """
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"策略 Schema 不存在：{SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=strategy, schema=schema)
    except jsonschema.ValidationError as e:
        raise StrategyValidationError(f"策略格式錯誤：{e.message}") from e

    return True


# ─── 目標持倉計算 ─────────────────────────────────────────────────────────────

def get_target_positions(
    portfolio_value: float,
    strategy: dict,
    top10: Optional[list[dict]] = None,
) -> dict[str, int]:
    """
    依策略計算各股目標持倉股數（整數股）

    規則：
    - 每檔使用總資金 per_position_pct %（預設 10%）
    - 只買整數股（無條件捨去）
    - 資金不足以買 1 股時，該檔跳過

    參數：
        portfolio_value  帳戶總淨值（現金 + 持倉市值）
        strategy         策略 JSON dict
        top10            預先傳入的 Top10 清單（None 時自動呼叫市場資料）

    回傳：{ "AAPL": 5, "MSFT": 3, ... }

    ⚠️ 此結果僅供研究參考，不構成投資建議。
    """
    if portfolio_value <= 0:
        return {}

    if top10 is None:
        n = strategy["selection"].get("n", 10)
        top10 = get_nasdaq_top10()
        top10 = top10[:n]

    per_pct = strategy["allocation"]["per_position_pct"] / 100.0
    per_value = portfolio_value * per_pct

    targets: dict[str, int] = {}
    for stock in top10:
        symbol = stock.get("symbol")
        price  = stock.get("price") or get_stock_price(symbol)
        if not price or price <= 0:
            logger.warning("跳過 %s（無法取得股價）", symbol)
            continue
        qty = int(per_value / price)   # 整數股，無條件捨去
        if qty > 0:
            targets[symbol] = qty
        else:
            logger.warning("跳過 %s（資金不足以買 1 股，需 $%.2f，每股 $%.2f）",
                           symbol, per_value, price)

    logger.info("目標持倉計算完成：%s", targets)
    return targets


# ─── 關注清單 ─────────────────────────────────────────────────────────────────

def get_watchlist_data(strategy: dict) -> dict[str, list[dict]]:
    """
    依策略設定取得關注清單各類別的股票即時資料

    回傳格式：
    {
        "科技龍頭": [{"symbol": "AAPL", "price": 195.0, ...}, ...],
        "AI 概念":  [...],
        "ETF":     [...],
    }
    """
    categories = strategy.get("watchlist_categories", [])
    result = {}
    for cat in categories:
        name    = cat.get("name", "")
        symbols = cat.get("symbols", [])
        if symbols:
            result[name] = get_multi_stock_info(symbols)
    return result
