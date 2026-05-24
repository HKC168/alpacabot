"""
dashboard/app.py
AlpacaBot Streamlit 儀錶板（Phase 7）

啟動：streamlit run dashboard/app.py

功能：
- 多帳戶選擇
- 現金水位、NAV、回撤卡片
- NAV 走勢圖（可疊加 NASDAQ / S&P500 基準）
- 持倉清單（含 1D / 1W / 1M 報酬率）
- NASDAQ Top10 股票（含 P/E）
- 三大關注類別
- 歷史報告回查

⚠️ 本儀錶板所有資訊僅供研究參考，不構成投資建議。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.account_loader import load_accounts
from src.report_generator import load_report, list_report_dates, get_nav_history

# ─── 頁面設定 ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AlpacaBot Dashboard",
    page_icon="📊",
    layout="wide",
)

# ─── 樣式 ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.metric-card {
    background: #fff7f0; border: 1px solid #e06c1f;
    border-radius: 12px; padding: 16px; text-align: center;
}
.metric-label { font-size: 13px; color: #888; margin-bottom: 4px; }
.metric-value { font-size: 26px; font-weight: bold; color: #333; }
.metric-change { font-size: 14px; font-weight: bold; }
.up   { color: #2e9e5b; }
.down { color: #c0392b; }
.disclaimer {
    font-size: 11px; color: #aaa; padding: 10px;
    border-top: 1px solid #eee; margin-top: 20px;
}
</style>
""", unsafe_allow_html=True)


# ─── 輔助函式 ─────────────────────────────────────────────────────────────────

def color_pct(val):
    """依正負值回傳顏色標記"""
    if val is None:
        return "N/A"
    arrow = "▲" if val >= 0 else "▼"
    color = "green" if val >= 0 else "red"
    return f"<span style='color:{color}'>{arrow} {abs(val):.2f}%</span>"


def fmt_usd(val):
    return f"${val:,.2f}" if val is not None else "N/A"


@st.cache_data(ttl=300)
def fetch_benchmark_data(period="3mo"):
    """取得 NASDAQ 和 S&P500 歷史資料（快取 5 分鐘）"""
    try:
        nasdaq = yf.Ticker("^IXIC").history(period=period)["Close"]
        sp500  = yf.Ticker("^GSPC").history(period=period)["Close"]
        return nasdaq, sp500
    except Exception:
        return None, None


def load_latest_report(account_id: str) -> dict:
    """載入最新報告（找不到時回傳空字典）"""
    dates = list_report_dates(account_id)
    if not dates:
        return {}
    return load_report(account_id, dates[0]) or {}


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://alpaca.markets/favicon.ico", width=32)
    st.title("AlpacaBot")
    st.caption("⚠️ 本平台資訊僅供研究參考，不構成投資建議")
    st.divider()

    # 帳戶選擇
    try:
        accounts    = load_accounts()
        account_ids = [a.id for a in accounts]
        account_names = {a.id: a.name for a in accounts}
    except Exception:
        account_ids   = ["PA3CVCWGFPAM"]
        account_names = {"PA3CVCWGFPAM": "Han Paper Account"}

    selected_id = st.selectbox(
        "選擇帳戶",
        account_ids,
        format_func=lambda x: f"{account_names.get(x, x)} ({x})",
    )

    st.divider()
    if st.button("🔄 重新整理資料"):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"最後更新：{date.today()}")


# ─── 載入報告資料 ─────────────────────────────────────────────────────────────

report = load_latest_report(selected_id)
nav_history = get_nav_history(selected_id)

if not report:
    st.warning(f"⚠️ 帳戶 {selected_id} 尚無報告資料。請先執行 `python src/main.py --mode report`")
    st.stop()

nav      = report.get("nav", {})
drawdown = report.get("drawdown", {})
bench    = report.get("benchmark", {})
holdings = report.get("holdings", [])
top10    = report.get("top10_today", [])
watchlist = report.get("watchlist", {})
orders   = report.get("orders_today", [])
report_date = report.get("report_date", "")
nav_cur  = nav.get("current", 0)
nav_chg  = nav.get("change_pct", 0)
cash     = report.get("cash", 0)
dd_cur   = drawdown.get("current_pct", 0)


# ─── 主標題 ───────────────────────────────────────────────────────────────────

st.title(f"📊 AlpacaBot Dashboard")
st.caption(f"帳戶：{account_names.get(selected_id, selected_id)} | 報告日期：{report_date}")
st.divider()


# ─── Tab 導航 ─────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🏠 概覽", "📋 持倉", "🏆 Top10", "📌 關注清單", "📅 歷史報告"]
)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 1：概覽
# ═════════════════════════════════════════════════════════════════════════════

with tab1:
    # ── 指標卡片 ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    arrow = "▲" if (nav_chg or 0) >= 0 else "▼"
    chg_cls = "up" if (nav_chg or 0) >= 0 else "down"

    with c1:
        st.markdown(f"""
        <div class="metric-card">
          <div class="metric-label">💵 現金水位</div>
          <div class="metric-value">{fmt_usd(cash)}</div>
        </div>""", unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="metric-card">
          <div class="metric-label">📈 帳戶淨值（NAV）</div>
          <div class="metric-value">{fmt_usd(nav_cur)}</div>
          <div class="metric-change {chg_cls}">{arrow} {abs(nav_chg or 0):.2f}% 今日</div>
        </div>""", unsafe_allow_html=True)

    with c3:
        dd_cls = "down" if dd_cur > 0 else "up"
        st.markdown(f"""
        <div class="metric-card">
          <div class="metric-label">📉 目前回撤</div>
          <div class="metric-value {dd_cls}">{dd_cur:.2f}%</div>
          <div class="metric-change" style="color:#888">最大：{drawdown.get('max_pct',0):.2f}%</div>
        </div>""", unsafe_allow_html=True)

    with c4:
        n_pct = bench.get("nasdaq_1d_pct")
        s_pct = bench.get("sp500_1d_pct")
        st.markdown(f"""
        <div class="metric-card">
          <div class="metric-label">🌐 今日基準</div>
          <div class="metric-change {'up' if (n_pct or 0) >= 0 else 'down'}">NASDAQ {(n_pct or 0):+.2f}%</div>
          <div class="metric-change {'up' if (s_pct or 0) >= 0 else 'down'}">S&P500 {(s_pct or 0):+.2f}%</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── NAV 走勢圖 ────────────────────────────────────────────────────────────
    st.subheader("📈 NAV 走勢圖")

    col_opt1, col_opt2, col_opt3 = st.columns(3)
    show_nasdaq = col_opt1.checkbox("☑ NASDAQ", value=True)
    show_sp500  = col_opt2.checkbox("☑ S&P500",  value=True)
    chart_period = col_opt3.selectbox("期間", ["1mo", "3mo", "6mo", "1y"], index=1)

    fig = go.Figure()

    # NAV 線
    if nav_history:
        df_nav = pd.DataFrame(nav_history)
        df_nav["date"] = pd.to_datetime(df_nav["date"])
        # 標準化：以第一天為基準 = 100
        base = df_nav["nav"].iloc[0]
        df_nav["nav_idx"] = df_nav["nav"] / base * 100
        fig.add_trace(go.Scatter(
            x=df_nav["date"], y=df_nav["nav_idx"],
            name="我的投資組合", line=dict(color="#e06c1f", width=2.5),
        ))

    # 基準線
    nasdaq_data, sp500_data = fetch_benchmark_data(chart_period)
    if show_nasdaq and nasdaq_data is not None and not nasdaq_data.empty:
        base_n = nasdaq_data.iloc[0]
        fig.add_trace(go.Scatter(
            x=nasdaq_data.index, y=nasdaq_data / base_n * 100,
            name="NASDAQ", line=dict(color="#2196F3", dash="dot"),
        ))
    if show_sp500 and sp500_data is not None and not sp500_data.empty:
        base_s = sp500_data.iloc[0]
        fig.add_trace(go.Scatter(
            x=sp500_data.index, y=sp500_data / base_s * 100,
            name="S&P500", line=dict(color="#9C27B0", dash="dash"),
        ))

    fig.update_layout(
        yaxis_title="相對績效（基準=100）",
        xaxis_title="日期",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── 回撤圖 ────────────────────────────────────────────────────────────────
    if nav_history and len(nav_history) > 1:
        st.subheader("📉 回撤走勢")
        df_dd = pd.DataFrame(nav_history)
        df_dd["date"] = pd.to_datetime(df_dd["date"])
        df_dd["peak"] = df_dd["nav"].cummax()
        df_dd["drawdown_pct"] = (df_dd["nav"] - df_dd["peak"]) / df_dd["peak"] * 100

        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=df_dd["date"], y=df_dd["drawdown_pct"],
            fill="tozeroy", name="回撤%",
            line=dict(color="#c0392b"), fillcolor="rgba(192,57,43,0.15)",
        ))
        fig_dd.update_layout(
            yaxis_title="回撤 %", xaxis_title="日期", height=250,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_dd, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 2：持倉清單
# ═════════════════════════════════════════════════════════════════════════════

with tab2:
    st.subheader("📋 目前持倉")
    if not holdings:
        st.info("目前無持倉")
    else:
        rows = []
        for h in holdings:
            pl  = h.get("unrealized_pl", 0)
            plc = h.get("unrealized_plpc", 0) * 100
            rows.append({
                "股票": h["symbol"],
                "股數": int(h["qty"]),
                "現價": f"${h['current_price']:,.2f}",
                "市值": f"${h['market_value']:,.2f}",
                "平均成本": f"${h['avg_cost']:,.2f}",
                "未實現損益": f"${pl:+,.2f}",
                "損益%": f"{plc:+.2f}%",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # 今日委託
    if orders:
        st.subheader("📝 今日委託")
        order_rows = []
        for o in orders:
            order_rows.append({
                "股票": o["symbol"],
                "方向": "買進" if o["side"] == "buy" else "賣出",
                "股數": int(o.get("qty", 0)),
                "狀態": o.get("status", ""),
                "成交均價": f"${o.get('filled_avg_price', 0):,.2f}",
                "時間": o.get("created_at", "")[:16],
            })
        st.dataframe(pd.DataFrame(order_rows), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 3：NASDAQ Top 10
# ═════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("🏆 今日 NASDAQ Top 10")
    st.caption("⚠️ 以下排名依市值排序，僅供資訊整理與研究參考，不構成投資建議")

    if not top10:
        st.info("暫無 Top10 資料，請重新整理或先執行日報")
    else:
        rows = []
        for s in top10:
            rows.append({
                "#":    s.get("rank", ""),
                "股票": s.get("symbol", ""),
                "公司": s.get("name", ""),
                "市值": f"${s.get('market_cap', 0)/1e12:.2f}T",
                "股價": f"${s.get('price', 0):,.2f}",
                "P/E": s.get("pe_ratio", "N/A"),
                "1D%": f"{s.get('1d_pct', 0) or 0:+.2f}%",
                "1W%": f"{s.get('1w_pct', 0) or 0:+.2f}%",
                "1M%": f"{s.get('1m_pct', 0) or 0:+.2f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # 明日預測
    pred = report.get("prediction_tomorrow", [])
    if pred:
        st.subheader("🔮 明日預測 Top 10")
        st.caption("⚠️ 預測僅依今日市值排名推估，不構成投資建議")
        pred_rows = [{"#": p["rank"], "股票": p["symbol"], "說明": p.get("reason", "")}
                     for p in pred]
        st.dataframe(pd.DataFrame(pred_rows), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 4：關注清單
# ═════════════════════════════════════════════════════════════════════════════

with tab4:
    st.subheader("📌 關注清單")
    st.caption("⚠️ 以下股票資訊僅供研究參考，不構成投資建議")

    if not watchlist:
        st.info("無關注清單資料（請確認策略 JSON 含 watchlist_categories）")
    else:
        cat_tabs = st.tabs(list(watchlist.keys()))
        for tab, (cat_name, stocks) in zip(cat_tabs, watchlist.items()):
            with tab:
                if not stocks:
                    st.info(f"{cat_name} 無資料")
                    continue
                rows = []
                for s in stocks:
                    rows.append({
                        "股票":  s.get("symbol", ""),
                        "股價":  f"${s.get('price', 0):,.2f}" if s.get("price") else "N/A",
                        "P/E":   s.get("pe_ratio", "N/A"),
                        "1D%":   f"{s.get('1d_pct', 0) or 0:+.2f}%",
                        "1W%":   f"{s.get('1w_pct', 0) or 0:+.2f}%",
                        "1M%":   f"{s.get('1m_pct', 0) or 0:+.2f}%",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 5：歷史報告
# ═════════════════════════════════════════════════════════════════════════════

with tab5:
    st.subheader("📅 歷史報告查詢")

    dates = list_report_dates(selected_id)
    if not dates:
        st.info("尚無歷史報告")
    else:
        selected_date = st.selectbox("選擇日期", dates)
        hist_report = load_report(selected_id, selected_date)

        if hist_report:
            h_nav  = hist_report.get("nav", {})
            h_dd   = hist_report.get("drawdown", {})
            h_bench = hist_report.get("benchmark", {})

            hc1, hc2, hc3 = st.columns(3)
            hc1.metric("現金", fmt_usd(hist_report.get("cash")))
            hc2.metric("NAV", fmt_usd(h_nav.get("current")),
                       f"{h_nav.get('change_pct', 0):+.2f}%")
            hc3.metric("回撤", f"{h_dd.get('current_pct', 0):.2f}%")

            st.json(hist_report, expanded=False)
        else:
            st.warning("找不到該日期的報告")


# ─── 頁尾免責聲明 ─────────────────────────────────────────────────────────────

st.markdown("""
<div class="disclaimer">
⚠️ <b>投資風險免責聲明</b>：本儀錶板所有資訊（排名、績效、預測）僅供資訊整理與研究參考，
<b>不構成任何投資建議</b>。股票市場具有風險，過去績效不代表未來結果。<br>
AlpacaBot 自動交易系統 | 由 Python + Alpaca API 驅動
</div>
""", unsafe_allow_html=True)
