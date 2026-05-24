"""
dashboard/app.py
AlpacaBot 雲端儀錶板 — 不依賴本地電腦，隨時可用

部署方式：
  本地：  streamlit run dashboard/app.py
  雲端：  部署到 Streamlit Cloud（https://share.streamlit.io）
          在 App Settings → Secrets 貼入 .streamlit/secrets.toml.example 的內容

資料來源（自動偵測，無需手動切換）：
  🟢 Live   → Alpaca API 即時查詢
  🟡 Cached → 最新 GitHub Actions 產生的報告（API 失敗時自動降級）
  🔴 N/A    → 尚無任何資料

⚠️ 本儀錶板所有資訊僅供資訊整理與研究參考，不構成投資建議。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from dashboard.data_layer import (
    DataSource, get_accounts_list, get_account_config,
    get_full_dashboard_data, get_available_report_dates,
    get_report_by_date, has_streamlit_secrets,
)

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
    background:#fff7f0;border:1px solid #e06c1f;
    border-radius:12px;padding:16px;text-align:center;margin-bottom:8px;
}
.metric-label { font-size:13px;color:#888;margin-bottom:4px; }
.metric-value { font-size:26px;font-weight:bold;color:#333; }
.metric-change { font-size:14px;font-weight:bold; }
.up   { color:#2e9e5b; }
.down { color:#c0392b; }
.src-live    { color:#2e9e5b;font-size:12px; }
.src-cached  { color:#f0a500;font-size:12px; }
.src-unavail { color:#c0392b;font-size:12px; }
.disclaimer  { font-size:11px;color:#aaa;padding:10px;border-top:1px solid #eee;margin-top:20px; }
</style>
""", unsafe_allow_html=True)


# ─── 輔助函式 ─────────────────────────────────────────────────────────────────

def source_badge(source: str) -> str:
    """資料來源徽章（顯示在 Sidebar）"""
    if source == DataSource.LIVE:
        return "🟢 即時 Live"
    elif source == DataSource.CACHED_REPORT:
        return "🟡 快取報告"
    return "🔴 無資料"


def fmt_usd(val) -> str:
    try:
        return f"${float(val):,.2f}"
    except Exception:
        return "N/A"


def fmt_pct(val, decimals=2) -> str:
    try:
        v = float(val)
        arrow = "▲" if v >= 0 else "▼"
        return f"{arrow} {abs(v):.{decimals}f}%"
    except Exception:
        return "N/A"


@st.cache_data(ttl=300)
def cached_benchmark(period="3mo"):
    """基準指數歷史資料（快取 5 分鐘）"""
    try:
        nasdaq = yf.Ticker("^IXIC").history(period=period)["Close"]
        sp500  = yf.Ticker("^GSPC").history(period=period)["Close"]
        return nasdaq, sp500
    except Exception:
        return None, None


@st.cache_data(ttl=60)
def cached_dashboard_data(account_id: str) -> dict:
    """全部資料（快取 60 秒，下次刷新自動更新）"""
    return get_full_dashboard_data(account_id)


# ═════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 📊 AlpacaBot")

    # 設定來源指示
    if has_streamlit_secrets():
        st.success("🔐 Secrets 已設定", icon="✅")
    else:
        st.warning("⚠️ 使用本地設定（account_config.json + env）")

    st.divider()

    # 帳戶選擇
    account_ids = get_accounts_list()
    if not account_ids:
        st.error("找不到任何帳戶設定。\n請設定 Streamlit Secrets 或 account_config.json")
        st.stop()

    selected_id = st.selectbox(
        "帳戶",
        account_ids,
        format_func=lambda x: get_account_config(x).get("name", x) + f" ({x})",
    )

    st.divider()

    # 刷新控制
    if st.button("🔄 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"快取：60秒自動更新\n最後刷新：{datetime.now().strftime('%H:%M:%S')}")

    st.divider()
    st.caption("⚠️ 本平台資訊僅供研究參考\n不構成投資建議")


# ─── 載入資料 ─────────────────────────────────────────────────────────────────

with st.spinner("載入資料中..."):
    data = cached_dashboard_data(selected_id)

account_result  = data["account_info"]
positions_result = data["positions"]
orders_result   = data["orders"]
report_result   = data["latest_report"]
nav_history     = data["nav_history"]

account_info = account_result.data or {}
positions    = positions_result.data or []
orders       = orders_result.data or []
report       = report_result.data or {}

# 從最新報告補充市場資料
top10     = report.get("top10_today", [])
watchlist = report.get("watchlist", {})
benchmark = report.get("benchmark", {})
drawdown  = report.get("drawdown", {})
nav_info  = report.get("nav", {})
report_date = report.get("report_date", "尚無報告")

# 帳戶數字（優先 Live API，備援報告）
cash     = account_info.get("cash",   report.get("cash",   0))
equity   = account_info.get("equity", report.get("equity", 0))
nav_chg  = nav_info.get("change_pct", 0)
dd_cur   = drawdown.get("current_pct", 0)
dd_max   = drawdown.get("max_pct", 0)


# ═════════════════════════════════════════════════════════════════════════════
# 主標題
# ═════════════════════════════════════════════════════════════════════════════

col_title, col_src = st.columns([4, 1])
with col_title:
    cfg_name = get_account_config(selected_id).get("name", selected_id)
    st.title(f"📊 {cfg_name}")
    st.caption(f"帳戶：{selected_id}  |  報告日期：{report_date}")
with col_src:
    st.markdown(f"<div style='margin-top:20px;text-align:right'>{source_badge(account_result.source)}</div>",
                unsafe_allow_html=True)
    if account_result.error:
        st.caption(f"⚠️ {account_result.error[:60]}")

st.divider()

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🏠 概覽", "📋 持倉", "🏆 Top10", "📌 關注清單", "📅 歷史報告"]
)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 1：概覽
# ═════════════════════════════════════════════════════════════════════════════

with tab1:
    # ── 指標卡片 ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    chg_cls = "up" if (nav_chg or 0) >= 0 else "down"

    with c1:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">💵 現金水位</div>
          <div class="metric-value">{fmt_usd(cash)}</div>
          <div class="metric-change {source_badge(account_result.source).split()[0]}">{source_badge(account_result.source)}</div>
        </div>""", unsafe_allow_html=True)

    with c2:
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">📈 帳戶淨值（NAV）</div>
          <div class="metric-value">{fmt_usd(equity)}</div>
          <div class="metric-change {chg_cls}">{fmt_pct(nav_chg)} 今日</div>
        </div>""", unsafe_allow_html=True)

    with c3:
        dd_cls = "down" if dd_cur > 0 else "up"
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">📉 目前回撤</div>
          <div class="metric-value {dd_cls}">{dd_cur:.2f}%</div>
          <div class="metric-change" style="color:#888">最大：{dd_max:.2f}%</div>
        </div>""", unsafe_allow_html=True)

    with c4:
        n_pct = benchmark.get("nasdaq_1d_pct") or 0
        s_pct = benchmark.get("sp500_1d_pct") or 0
        st.markdown(f"""<div class="metric-card">
          <div class="metric-label">🌐 今日基準</div>
          <div class="metric-change {'up' if n_pct >= 0 else 'down'}">NASDAQ {n_pct:+.2f}%</div>
          <div class="metric-change {'up' if s_pct >= 0 else 'down'}">S&P500 {s_pct:+.2f}%</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── NAV 走勢圖 ────────────────────────────────────────────────────────────
    st.subheader("📈 NAV 走勢（vs 基準）")

    col_chk1, col_chk2, col_period = st.columns(3)
    show_nasdaq  = col_chk1.checkbox("☑ NASDAQ",  value=True)
    show_sp500   = col_chk2.checkbox("☑ S&P500",  value=True)
    chart_period = col_period.selectbox("期間", ["1mo", "3mo", "6mo", "1y"], index=1)

    fig = go.Figure()

    if nav_history:
        df_nav = pd.DataFrame(nav_history)
        df_nav["date"] = pd.to_datetime(df_nav["date"])
        base = df_nav["nav"].iloc[0]
        df_nav["idx"] = df_nav["nav"] / base * 100
        fig.add_trace(go.Scatter(
            x=df_nav["date"], y=df_nav["idx"],
            name="我的投資組合", line=dict(color="#e06c1f", width=2.5),
        ))
    else:
        st.info("📊 NAV 歷史尚無資料（GitHub Actions 執行後會自動產生）")

    nasdaq_data, sp500_data = cached_benchmark(chart_period)
    if show_nasdaq and nasdaq_data is not None and len(nasdaq_data) > 0:
        base_n = nasdaq_data.iloc[0]
        fig.add_trace(go.Scatter(
            x=nasdaq_data.index, y=nasdaq_data / base_n * 100,
            name="NASDAQ", line=dict(color="#2196F3", dash="dot"),
        ))
    if show_sp500 and sp500_data is not None and len(sp500_data) > 0:
        base_s = sp500_data.iloc[0]
        fig.add_trace(go.Scatter(
            x=sp500_data.index, y=sp500_data / base_s * 100,
            name="S&P500", line=dict(color="#9C27B0", dash="dash"),
        ))

    fig.update_layout(
        yaxis_title="相對績效（起始=100）", xaxis_title="日期",
        hovermode="x unified", height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── 回撤圖 ────────────────────────────────────────────────────────────────
    if nav_history and len(nav_history) > 1:
        st.subheader("📉 回撤走勢")
        df_dd = pd.DataFrame(nav_history)
        df_dd["date"] = pd.to_datetime(df_dd["date"])
        df_dd["peak"] = df_dd["nav"].cummax()
        df_dd["dd"]   = (df_dd["nav"] - df_dd["peak"]) / df_dd["peak"] * 100
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=df_dd["date"], y=df_dd["dd"], fill="tozeroy",
            name="回撤%", line=dict(color="#c0392b"),
            fillcolor="rgba(192,57,43,0.12)",
        ))
        fig2.update_layout(yaxis_title="回撤%", height=230,
                           margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig2, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 2：持倉
# ═════════════════════════════════════════════════════════════════════════════

with tab2:
    src_badge = source_badge(positions_result.source)
    st.subheader(f"📋 持倉清單  {src_badge}")

    if not positions:
        st.info("目前無持倉")
    else:
        rows = []
        for h in positions:
            pl  = h.get("unrealized_pl", 0)
            plc = h.get("unrealized_plpc", 0) * 100
            rows.append({
                "股票":     h["symbol"],
                "股數":     int(h["qty"]),
                "現價":     fmt_usd(h.get("current_price", 0)),
                "市值":     fmt_usd(h.get("market_value", 0)),
                "平均成本": fmt_usd(h.get("avg_cost", 0)),
                "未實現損益": fmt_usd(pl),
                "損益%":   f"{plc:+.2f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # 今日委託
    st.subheader(f"📝 今日委託  {source_badge(orders_result.source)}")
    if not orders:
        st.info("今日無委託記錄")
    else:
        order_rows = [{
            "股票":   o["symbol"],
            "方向":   "買進" if o.get("side") == "buy" else "賣出",
            "股數":   int(o.get("qty", 0)),
            "狀態":   o.get("status", ""),
            "成交均價": fmt_usd(o.get("filled_avg_price", 0)),
            "時間":   (o.get("created_at", "") or "")[:16],
        } for o in orders]
        st.dataframe(pd.DataFrame(order_rows), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 3：NASDAQ Top 10
# ═════════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("🏆 今日 NASDAQ Top 10")
    st.caption("⚠️ 資料來自最新日報（GitHub Actions 每日更新）。排名僅供研究參考，不構成投資建議。")

    if not top10:
        st.info("暫無 Top10 資料。請確認 GitHub Actions 已成功執行日報。")
    else:
        rows = [{
            "#":    s.get("rank", ""),
            "股票": s.get("symbol", ""),
            "公司": s.get("name", ""),
            "市值": f"${s.get('market_cap', 0)/1e12:.2f}T",
            "股價": fmt_usd(s.get("price", 0)),
            "P/E":  s.get("pe_ratio", "N/A"),
            "1D%":  f"{s.get('1d_pct', 0) or 0:+.2f}%",
            "1W%":  f"{s.get('1w_pct', 0) or 0:+.2f}%",
            "1M%":  f"{s.get('1m_pct', 0) or 0:+.2f}%",
        } for s in top10]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # 明日預測
    pred = report.get("prediction_tomorrow", [])
    if pred:
        st.subheader("🔮 明日預測 Top 10")
        st.caption("⚠️ 預測依市值推估，不構成投資建議")
        st.dataframe(pd.DataFrame([{
            "#": p["rank"], "股票": p["symbol"], "說明": p.get("reason", "")
        } for p in pred]), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 4：關注清單
# ═════════════════════════════════════════════════════════════════════════════

with tab4:
    st.subheader("📌 關注清單")
    st.caption("⚠️ 以下資訊僅供研究參考，不構成投資建議")

    if not watchlist:
        st.info("無關注清單（請確認策略 JSON 含 watchlist_categories，且日報已產生）")
    else:
        cat_tabs = st.tabs(list(watchlist.keys()))
        for tab, (cat_name, stocks) in zip(cat_tabs, watchlist.items()):
            with tab:
                if not stocks:
                    st.info(f"{cat_name} 暫無資料")
                    continue
                rows = [{
                    "股票": s.get("symbol", ""),
                    "股價": fmt_usd(s.get("price", 0)) if s.get("price") else "N/A",
                    "P/E":  s.get("pe_ratio", "N/A"),
                    "1D%":  f"{s.get('1d_pct', 0) or 0:+.2f}%",
                    "1W%":  f"{s.get('1w_pct', 0) or 0:+.2f}%",
                    "1M%":  f"{s.get('1m_pct', 0) or 0:+.2f}%",
                } for s in stocks]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Tab 5：歷史報告
# ═════════════════════════════════════════════════════════════════════════════

with tab5:
    st.subheader("📅 歷史報告查詢")

    dates = get_available_report_dates(selected_id)
    if not dates:
        st.info("尚無歷史報告（GitHub Actions 執行後自動產生）")
    else:
        selected_date = st.selectbox("選擇日期", dates)
        hist = get_report_by_date(selected_id, selected_date)

        if hist.ok:
            r = hist.data
            h_nav = r.get("nav", {})
            h_dd  = r.get("drawdown", {})
            h_b   = r.get("benchmark", {})

            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("現金",    fmt_usd(r.get("cash")))
            hc2.metric("NAV",     fmt_usd(h_nav.get("current")),
                                  f"{h_nav.get('change_pct', 0):+.2f}%")
            hc3.metric("回撤",    f"{h_dd.get('current_pct', 0):.2f}%")
            hc4.metric("NASDAQ",  f"{h_b.get('nasdaq_1d_pct', 'N/A')}%")

            with st.expander("查看完整 JSON"):
                st.json(r)
        else:
            st.warning("找不到該日期的報告")


# ─── 頁尾免責聲明 ─────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
⚠️ <b>投資風險免責聲明</b>：本儀錶板所有資訊（排名、績效、預測）
僅供資訊整理與研究參考，<b>不構成任何投資建議</b>。
股票市場具有風險，過去績效不代表未來結果。<br>
AlpacaBot 自動交易系統 | 資料來源：Alpaca API + Yahoo Finance
</div>
""", unsafe_allow_html=True)
