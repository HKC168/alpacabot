"""
tests/test_market_data.py
Phase 2 測試案例 — 市場資料模組

執行 Mock 測試：pytest tests/test_market_data.py -v -m "not live"
執行 Live 測試：pytest tests/test_market_data.py -v -m live -s
"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from src.market_data import (
    get_stock_price,
    get_returns,
    get_pe_ratio,
    get_market_cap,
    get_nasdaq_top10,
    get_benchmark_returns,
    get_multi_stock_info,
    _calc_pct_change,
    NASDAQ_UNIVERSE,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_close_series(prices: list[float]) -> pd.Series:
    """建立假的收盤價 Series"""
    idx = pd.date_range("2026-01-01", periods=len(prices), freq="B")
    return pd.Series(prices, index=idx)


def _mock_ticker_history(close_prices: list[float]):
    """建立假的 yf.Ticker().history() 回傳物件"""
    hist = pd.DataFrame({"Close": close_prices})
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    return mock_ticker


# ─── Test 1: 個股即時股價 ────────────────────────────────────────────────────

class TestGetStockPrice:

    def test_returns_positive_float(self):
        """正常情況：回傳大於 0 的 float"""
        mock_ticker = _mock_ticker_history([190.0, 195.0])
        with patch("yfinance.Ticker", return_value=mock_ticker):
            price = get_stock_price("AAPL")
        assert isinstance(price, float)
        assert price > 0
        assert price == 195.0

    def test_returns_none_on_empty_data(self):
        """無資料時回傳 None"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            price = get_stock_price("FAKE")
        assert price is None

    def test_returns_none_on_exception(self):
        """發生例外時回傳 None，不拋出錯誤"""
        with patch("yfinance.Ticker", side_effect=Exception("網路錯誤")):
            price = get_stock_price("AAPL")
        assert price is None

    def test_price_is_rounded(self):
        """股價應四捨五入到 4 位小數"""
        mock_ticker = _mock_ticker_history([195.123456789])
        with patch("yfinance.Ticker", return_value=mock_ticker):
            price = get_stock_price("AAPL")
        assert price == round(195.123456789, 4)


# ─── Test 2: 1D / 1W / 1M 報酬率 ────────────────────────────────────────────

class TestGetReturns:

    def _build_mock(self, prices: list[float]):
        hist = pd.DataFrame({"Close": prices})
        mock = MagicMock()
        mock.history.return_value = hist
        return mock

    def test_returns_all_three_fields(self):
        """回傳 1d_pct、1w_pct、1m_pct 三個欄位"""
        prices = [100.0] * 30
        prices[-1] = 105.0   # 最後一天漲 5%
        with patch("yfinance.Ticker", return_value=self._build_mock(prices)):
            result = get_returns("AAPL")
        assert "1d_pct" in result
        assert "1w_pct" in result
        assert "1m_pct" in result
        assert result["symbol"] == "AAPL"

    def test_1d_pct_calculation_correct(self):
        """1D 報酬率計算正確：(新 - 舊) / 舊 × 100"""
        prices = [100.0, 102.0]  # 漲 2%
        with patch("yfinance.Ticker", return_value=self._build_mock(prices)):
            result = get_returns("AAPL")
        assert result["1d_pct"] == pytest.approx(2.0, rel=1e-3)

    def test_insufficient_data_returns_none(self):
        """資料不足時對應欄位回傳 None"""
        prices = [100.0, 101.0]   # 只有 2 筆，無法算 1w/1m
        with patch("yfinance.Ticker", return_value=self._build_mock(prices)):
            result = get_returns("AAPL")
        assert result["1w_pct"] is None
        assert result["1m_pct"] is None

    def test_exception_returns_none_fields(self):
        """發生例外時所有報酬率欄位回傳 None"""
        with patch("yfinance.Ticker", side_effect=Exception("錯誤")):
            result = get_returns("AAPL")
        assert result["1d_pct"] is None
        assert result["1w_pct"] is None
        assert result["1m_pct"] is None

    def test_negative_return(self):
        """下跌時報酬率應為負數"""
        prices = [100.0, 95.0]  # 跌 5%
        with patch("yfinance.Ticker", return_value=self._build_mock(prices)):
            result = get_returns("AAPL")
        assert result["1d_pct"] == pytest.approx(-5.0, rel=1e-3)


# ─── Test 3: 本益比（P/E Ratio）─────────────────────────────────────────────

class TestGetPERatio:

    def _make_ticker_info(self, pe_value):
        mock = MagicMock()
        mock.info = {"trailingPE": pe_value}
        return mock

    def test_returns_float_when_available(self):
        """正常情況：回傳 float"""
        with patch("yfinance.Ticker", return_value=self._make_ticker_info(28.5)):
            pe = get_pe_ratio("AAPL")
        assert isinstance(pe, float)
        assert pe == 28.5

    def test_returns_none_when_no_pe(self):
        """無本益比資料時回傳 None"""
        mock = MagicMock()
        mock.info = {"trailingPE": None}
        with patch("yfinance.Ticker", return_value=mock):
            pe = get_pe_ratio("FAKE")
        assert pe is None

    def test_returns_none_on_exception(self):
        """發生例外時回傳 None"""
        with patch("yfinance.Ticker", side_effect=Exception("錯誤")):
            pe = get_pe_ratio("AAPL")
        assert pe is None

    def test_pe_is_rounded_to_2dp(self):
        """本益比應四捨五入到 2 位小數"""
        with patch("yfinance.Ticker", return_value=self._make_ticker_info(28.567)):
            pe = get_pe_ratio("AAPL")
        assert pe == 28.57


# ─── Test 4: NASDAQ Top10 篩選 ───────────────────────────────────────────────

class TestGetNasdaqTop10:

    def _make_stock_info(self, symbol: str, market_cap: float) -> dict:
        return {
            "marketCap": market_cap,
            "shortName": f"{symbol} Inc.",
            "currentPrice": 100.0,
            "trailingPE": 25.0,
        }

    def test_returns_exactly_10_stocks(self):
        """回傳恰好 10 筆"""
        mock_returns = {"symbol": "X", "1d_pct": 1.0, "1w_pct": 2.0, "1m_pct": 3.0}

        def fake_ticker(sym):
            m = MagicMock()
            caps = {s: (15 - i) * 1e12 for i, s in enumerate(NASDAQ_UNIVERSE[:15])}
            m.info = self._make_stock_info(sym, caps.get(sym, 1e10))
            hist = pd.DataFrame({"Close": [95.0, 100.0]})
            m.history.return_value = hist
            return m

        with patch("yfinance.Ticker", side_effect=fake_ticker), \
             patch("src.market_data.get_returns", return_value=mock_returns):
            top10 = get_nasdaq_top10(NASDAQ_UNIVERSE[:20])

        assert len(top10) == 10

    def test_contains_required_fields(self):
        """每筆結果含必要欄位"""
        mock_returns = {"symbol": "X", "1d_pct": 1.0, "1w_pct": 2.0, "1m_pct": 3.0}

        def fake_ticker(sym):
            m = MagicMock()
            m.info = self._make_stock_info(sym, 1e12)
            m.history.return_value = pd.DataFrame({"Close": [95.0, 100.0]})
            return m

        with patch("yfinance.Ticker", side_effect=fake_ticker), \
             patch("src.market_data.get_returns", return_value=mock_returns):
            top10 = get_nasdaq_top10(NASDAQ_UNIVERSE[:15])

        required = {"rank", "symbol", "name", "market_cap", "price",
                    "pe_ratio", "1d_pct", "1w_pct", "1m_pct"}
        for stock in top10:
            assert required.issubset(stock.keys()), f"{stock['symbol']} 缺少欄位"

    def test_sorted_by_market_cap_descending(self):
        """結果應依市值由大到小排序"""
        mock_returns = {"symbol": "X", "1d_pct": 0.0, "1w_pct": 0.0, "1m_pct": 0.0}
        caps = {s: (20 - i) * 1e12 for i, s in enumerate(NASDAQ_UNIVERSE[:20])}

        def fake_ticker(sym):
            m = MagicMock()
            m.info = self._make_stock_info(sym, caps.get(sym, 1e10))
            m.history.return_value = pd.DataFrame({"Close": [95.0, 100.0]})
            return m

        with patch("yfinance.Ticker", side_effect=fake_ticker), \
             patch("src.market_data.get_returns", return_value=mock_returns):
            top10 = get_nasdaq_top10(NASDAQ_UNIVERSE[:20])

        market_caps = [s["market_cap"] for s in top10]
        assert market_caps == sorted(market_caps, reverse=True)

    def test_rank_starts_at_1(self):
        """第一名 rank 應為 1"""
        mock_returns = {"symbol": "X", "1d_pct": 0.0, "1w_pct": 0.0, "1m_pct": 0.0}

        def fake_ticker(sym):
            m = MagicMock()
            m.info = self._make_stock_info(sym, 1e12)
            m.history.return_value = pd.DataFrame({"Close": [95.0, 100.0]})
            return m

        with patch("yfinance.Ticker", side_effect=fake_ticker), \
             patch("src.market_data.get_returns", return_value=mock_returns):
            top10 = get_nasdaq_top10(NASDAQ_UNIVERSE[:15])

        assert top10[0]["rank"] == 1
        assert top10[-1]["rank"] == 10


# ─── Test 5: 基準指數報酬率 ──────────────────────────────────────────────────

class TestGetBenchmarkReturns:

    def test_returns_nasdaq_and_sp500_fields(self):
        """回傳含 nasdaq_1d_pct 和 sp500_1d_pct"""

        def fake_ticker(sym):
            m = MagicMock()
            m.history.return_value = pd.DataFrame({"Close": [100.0, 101.5]})
            return m

        with patch("yfinance.Ticker", side_effect=fake_ticker):
            result = get_benchmark_returns()

        assert "nasdaq_1d_pct" in result
        assert "sp500_1d_pct" in result

    def test_benchmark_pct_calculation(self):
        """基準報酬率計算正確（漲 1.5%）"""

        def fake_ticker(sym):
            m = MagicMock()
            m.history.return_value = pd.DataFrame({"Close": [100.0, 101.5]})
            return m

        with patch("yfinance.Ticker", side_effect=fake_ticker):
            result = get_benchmark_returns()

        assert result["nasdaq_1d_pct"] == pytest.approx(1.5, rel=1e-3)
        assert result["sp500_1d_pct"] == pytest.approx(1.5, rel=1e-3)

    def test_returns_none_on_exception(self):
        """發生例外時回傳 None 值，不拋出錯誤"""
        with patch("yfinance.Ticker", side_effect=Exception("網路錯誤")):
            result = get_benchmark_returns()
        assert result["nasdaq_1d_pct"] is None
        assert result["sp500_1d_pct"] is None


# ─── 輔助函式測試 ─────────────────────────────────────────────────────────────

class TestCalcPctChange:

    def test_basic_positive_change(self):
        s = _make_close_series([100.0] * 5 + [110.0])
        assert _calc_pct_change(s, 1) == pytest.approx(10.0, rel=1e-3)

    def test_negative_change(self):
        s = _make_close_series([100.0, 90.0])
        assert _calc_pct_change(s, 1) == pytest.approx(-10.0, rel=1e-3)

    def test_insufficient_data_returns_none(self):
        s = _make_close_series([100.0])
        assert _calc_pct_change(s, 1) is None

    def test_zero_base_returns_none(self):
        s = _make_close_series([0.0, 100.0])
        assert _calc_pct_change(s, 1) is None


# ─── Live 測試（需要網路）────────────────────────────────────────────────────

@pytest.mark.live
class TestLiveMarketData:
    """
    需要網路連線才能執行
    執行：pytest tests/test_market_data.py -v -m live -s
    """

    def test_live_stock_price_aapl(self):
        price = get_stock_price("AAPL")
        assert price is not None
        assert price > 0
        print(f"\n✅ AAPL 股價：${price:,.2f}")

    def test_live_returns_aapl(self):
        result = get_returns("AAPL")
        assert result["1d_pct"] is not None
        assert result["1w_pct"] is not None
        assert result["1m_pct"] is not None
        print(f"\n✅ AAPL 報酬率 — 1D:{result['1d_pct']:.2f}%  "
              f"1W:{result['1w_pct']:.2f}%  1M:{result['1m_pct']:.2f}%")

    def test_live_pe_ratio_aapl(self):
        pe = get_pe_ratio("AAPL")
        # AAPL 通常有 P/E，允許 None（若市場休市）
        print(f"\n✅ AAPL 本益比：{pe}")

    def test_live_benchmark_returns(self):
        result = get_benchmark_returns()
        assert "nasdaq_1d_pct" in result
        assert "sp500_1d_pct" in result
        print(f"\n✅ 基準 — NASDAQ:{result['nasdaq_1d_pct']}%  "
              f"S&P500:{result['sp500_1d_pct']}%")

    def test_live_nasdaq_top10(self):
        """Live Top10 測試（耗時較長，約 60 秒）"""
        # 只用前 15 支股票加快速度
        top10 = get_nasdaq_top10(NASDAQ_UNIVERSE[:15])
        assert len(top10) == 10
        print(f"\n✅ NASDAQ Top10：")
        for s in top10:
            print(f"   {s['rank']}. {s['symbol']:6s}  市值:${s['market_cap']/1e12:.1f}T  "
                  f"P/E:{s['pe_ratio']}  1D:{s['1d_pct']}%")
