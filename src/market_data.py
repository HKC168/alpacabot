"""
market_data.py
市場資料擷取模組（Phase 2）

提供：
- get_nasdaq_top10()       NASDAQ 市值前 10 大股票
- get_stock_price()        個股即時股價
- get_returns()            1D / 1W / 1M 歷史報酬率
- get_pe_ratio()           本益比（P/E Ratio）
- get_benchmark_returns()  NASDAQ / S&P500 基準日報酬
- get_multi_stock_info()   批次查詢多支股票完整資訊

資料來源：yfinance（Yahoo Finance，免費，無需 API Key）

⚠️ 本模組資料僅供資訊整理與研究參考，不構成任何投資建議。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ─── NASDAQ 大市值股票清單（定期更新，用於 Top10 篩選）────────────────────
NASDAQ_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO",
    "COST", "NFLX", "ASML", "AMD", "ADBE", "QCOM", "INTC", "CSCO",
    "INTU", "AMGN", "TXN", "ISRG", "BKNG", "VRTX", "REGN", "LRCX",
    "PANW", "MU", "ADI", "MELI", "KLAC", "MDLZ", "GILD", "SNPS",
    "CDNS", "PYPL", "CTAS", "NXPI", "ORLY", "FTNT", "MRVL", "WDAY",
    "PCAR", "ROP", "MCHP", "DXCM", "ZS", "TEAM", "CRWD", "ABNB",
    "IDXX", "CEG",
]

# 指數代號
NASDAQ_TICKER = "^IXIC"   # NASDAQ Composite
SP500_TICKER  = "^GSPC"   # S&P 500


# ─── 公用函式 ─────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    """安全轉換為 float，失敗回傳 default"""
    try:
        v = float(val)
        return v if pd.notna(v) else default
    except (TypeError, ValueError):
        return default


def _calc_pct_change(series: pd.Series, periods: int) -> Optional[float]:
    """
    計算 series 最近 periods 個交易日的報酬率（百分比）
    - periods=1  → 1 個交易日（約 1 天）
    - periods=5  → 5 個交易日（約 1 週）
    - periods=21 → 21 個交易日（約 1 個月）
    回傳 None 表示資料不足
    """
    if series is None or len(series) < periods + 1:
        return None
    old = series.iloc[-(periods + 1)]
    new = series.iloc[-1]
    if old == 0 or pd.isna(old) or pd.isna(new):
        return None
    return round((new - old) / old * 100, 4)


# ─── 主要 API ─────────────────────────────────────────────────────────────────

def get_stock_price(symbol: str) -> Optional[float]:
    """
    取得個股最新收盤價

    回傳：float 或 None（查詢失敗時）

    說明：這是股票在市場上的最新交易價格。
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        if hist.empty:
            logger.warning("get_stock_price: %s 無資料", symbol)
            return None
        return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        logger.error("get_stock_price(%s) 錯誤：%s", symbol, e)
        return None


def get_returns(symbol: str) -> dict:
    """
    計算個股 1 天、1 週、1 個月的報酬率（%）

    回傳格式：
    {
        "symbol": "AAPL",
        "1d_pct":  1.23,    # 1 個交易日報酬（%）
        "1w_pct":  3.45,    # 5 個交易日報酬（%）
        "1m_pct":  8.12,    # 21 個交易日報酬（%）
    }
    None 表示資料不足無法計算。

    說明：報酬率 = (現值 - 舊值) / 舊值 × 100
    """
    result = {"symbol": symbol, "1d_pct": None, "1w_pct": None, "1m_pct": None}
    try:
        hist = yf.Ticker(symbol).history(period="2mo")["Close"]
        result["1d_pct"] = _calc_pct_change(hist, 1)
        result["1w_pct"] = _calc_pct_change(hist, 5)
        result["1m_pct"] = _calc_pct_change(hist, 21)
    except Exception as e:
        logger.error("get_returns(%s) 錯誤：%s", symbol, e)
    return result


def get_pe_ratio(symbol: str) -> Optional[float]:
    """
    取得個股本益比（P/E Ratio，本益比 = 股價 / 每股盈餘）

    回傳：float 或 None（無法取得或公司虧損時）

    說明：本益比代表投資人願意為每 1 元獲利支付多少倍的價格，
          數字越低通常代表股票越便宜（但需結合產業背景判斷）。
    ⚠️ 本益比僅供參考，不構成投資建議。
    """
    try:
        info = yf.Ticker(symbol).info
        pe = info.get("trailingPE") or info.get("forwardPE")
        if pe is None or pd.isna(pe):
            return None
        return round(float(pe), 2)
    except Exception as e:
        logger.error("get_pe_ratio(%s) 錯誤：%s", symbol, e)
        return None


def get_market_cap(symbol: str) -> Optional[float]:
    """
    取得個股市值（USD）

    說明：市值 = 股價 × 流通股數，代表市場對這家公司的整體估值。
    """
    try:
        info = yf.Ticker(symbol).info
        cap = info.get("marketCap")
        if cap is None or pd.isna(cap):
            return None
        return float(cap)
    except Exception as e:
        logger.error("get_market_cap(%s) 錯誤：%s", symbol, e)
        return None


def get_nasdaq_top10(universe: list[str] = NASDAQ_UNIVERSE) -> list[dict]:
    """
    從 NASDAQ 股票池中，依市值篩選出前 10 大股票

    回傳每筆欄位：
    {
        "rank":       1,
        "symbol":     "AAPL",
        "name":       "Apple Inc.",
        "market_cap": 3100000000000,
        "price":      195.00,
        "pe_ratio":   28.5,
        "1d_pct":     1.2,
        "1w_pct":     3.5,
        "1m_pct":     8.1,
    }

    ⚠️ 排名結果僅供資訊整理與研究參考，不構成任何投資建議。
    """
    logger.info("開始篩選 NASDAQ Top10，股票池大小：%d", len(universe))
    results = []

    for symbol in universe:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            cap = info.get("marketCap")
            if cap is None or pd.isna(cap):
                continue
            results.append({
                "symbol": symbol,
                "name": info.get("shortName", symbol),
                "market_cap": float(cap),
                "price": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
                "pe_ratio": round(float(info["trailingPE"]), 2)
                            if info.get("trailingPE") and pd.notna(info["trailingPE"]) else None,
            })
        except Exception as e:
            logger.warning("get_nasdaq_top10 跳過 %s：%s", symbol, e)
            continue

    # 依市值排序，取前 10
    results.sort(key=lambda x: x["market_cap"], reverse=True)
    top10 = results[:10]

    # 批次補充報酬率
    for i, stock in enumerate(top10):
        returns = get_returns(stock["symbol"])
        stock.update({
            "rank": i + 1,
            "1d_pct": returns["1d_pct"],
            "1w_pct": returns["1w_pct"],
            "1m_pct": returns["1m_pct"],
        })

    logger.info("NASDAQ Top10 篩選完成：%s", [s["symbol"] for s in top10])
    return top10


def get_benchmark_returns() -> dict:
    """
    取得 NASDAQ Composite 與 S&P 500 今日報酬率

    回傳：
    {
        "nasdaq_1d_pct": 0.52,   # NASDAQ 今日漲跌幅（%）
        "sp500_1d_pct":  0.31,   # S&P500 今日漲跌幅（%）
    }

    說明：這兩個是美股最重要的市場基準指數，用來比較我們的投資組合表現。
    """
    result = {"nasdaq_1d_pct": None, "sp500_1d_pct": None}
    try:
        for key, ticker_sym in [("nasdaq_1d_pct", NASDAQ_TICKER),
                                 ("sp500_1d_pct", SP500_TICKER)]:
            hist = yf.Ticker(ticker_sym).history(period="5d")["Close"]
            result[key] = _calc_pct_change(hist, 1)
    except Exception as e:
        logger.error("get_benchmark_returns 錯誤：%s", e)
    return result


def get_multi_stock_info(symbols: list[str]) -> list[dict]:
    """
    批次查詢多支股票的完整資訊（股價 + 報酬率 + P/E）

    適用於儀錶板持倉清單和關注清單顯示
    """
    results = []
    for symbol in symbols:
        price = get_stock_price(symbol)
        returns = get_returns(symbol)
        pe = get_pe_ratio(symbol)
        results.append({
            "symbol": symbol,
            "price": price,
            "pe_ratio": pe,
            "1d_pct": returns["1d_pct"],
            "1w_pct": returns["1w_pct"],
            "1m_pct": returns["1m_pct"],
        })
    return results
