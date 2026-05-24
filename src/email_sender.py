"""
email_sender.py
Email 日報與通知模組（Phase 8）

功能：
- 每日 06:00 AM（ET）發送 HTML 日報
- 即時交易通知（由 notifier.py 觸發）
- 支援多帳戶各自發送至對應 email

⚠️ 所有 Email 內容均附有投資風險免責聲明。
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


# ─── SMTP 工具 ────────────────────────────────────────────────────────────────

def _smtp_config() -> dict:
    return {
        "host":     os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port":     int(os.environ.get("SMTP_PORT", "587")),
        "user":     os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
    }


def send_email(to: str, subject: str, html_body: str) -> bool:
    """
    發送 HTML Email

    回傳 True 表示成功，False 表示失敗（不拋例外，避免中斷主流程）
    """
    cfg = _smtp_config()
    if not cfg["user"] or not cfg["password"]:
        logger.warning("SMTP 未設定（SMTP_USER / SMTP_PASSWORD），跳過發送：%s", subject)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["user"]
        msg["To"]      = to
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["user"], [to], msg.as_string())

        logger.info("✉️  Email 已發送至 %s：%s", to, subject)
        return True
    except Exception as e:
        logger.error("Email 發送失敗：%s", e)
        return False


# ─── 日報 HTML 模板 ───────────────────────────────────────────────────────────

def _render_daily_report_html(report: dict) -> str:
    """將 JSON 報告 Model 渲染為 HTML Email（View）"""
    nav        = report.get("nav", {})
    drawdown   = report.get("drawdown", {})
    benchmark  = report.get("benchmark", {})
    holdings   = report.get("holdings", [])
    top10      = report.get("top10_today", [])
    watchlist  = report.get("watchlist", {})
    orders     = report.get("orders_today", [])
    acct_id    = report.get("account_id", "")
    acct_name  = report.get("account_name", "")
    report_date = report.get("report_date", "")

    nav_cur    = nav.get("current", 0)
    nav_chg    = nav.get("change_pct", 0)
    chg_color  = "#2e9e5b" if (nav_chg or 0) >= 0 else "#c0392b"
    chg_arrow  = "▲" if (nav_chg or 0) >= 0 else "▼"

    # ── 持倉表格 ────────────────────────────────────────────────────────────
    holdings_html = ""
    if holdings:
        rows = ""
        for h in holdings:
            pl  = h.get("unrealized_pl", 0)
            plc = h.get("unrealized_plpc", 0) * 100
            color = "#2e9e5b" if pl >= 0 else "#c0392b"
            rows += f"""<tr>
              <td>{h['symbol']}</td>
              <td>{int(h['qty'])}</td>
              <td>${h['current_price']:,.2f}</td>
              <td>${h['market_value']:,.2f}</td>
              <td style="color:{color}">{pl:+,.2f}</td>
              <td style="color:{color}">{plc:+.2f}%</td>
            </tr>"""
        holdings_html = f"""
        <h3 style="color:#e06c1f">📊 持倉清單</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%">
          <tr style="background:#e06c1f;color:#fff">
            <th>股票</th><th>股數</th><th>現價</th><th>市值</th><th>未實現損益</th><th>損益%</th>
          </tr>{rows}</table>"""
    else:
        holdings_html = "<p>目前無持倉</p>"

    # ── Top10 表格 ──────────────────────────────────────────────────────────
    top10_rows = ""
    for s in top10[:10]:
        c1d = "#2e9e5b" if (s.get("1d_pct") or 0) >= 0 else "#c0392b"
        top10_rows += f"""<tr>
          <td>{s.get('rank','')}</td>
          <td><b>{s.get('symbol','')}</b></td>
          <td>${s.get('market_cap',0)/1e12:.1f}T</td>
          <td>${s.get('price',0):,.2f}</td>
          <td>{s.get('pe_ratio','N/A')}</td>
          <td style="color:{c1d}">{s.get('1d_pct','N/A')}%</td>
          <td>{s.get('1w_pct','N/A')}%</td>
          <td>{s.get('1m_pct','N/A')}%</td>
        </tr>"""
    top10_html = f"""
    <h3 style="color:#e06c1f">🏆 今日 NASDAQ Top 10（⚠️ 僅供研究參考）</h3>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%">
      <tr style="background:#e06c1f;color:#fff">
        <th>#</th><th>股票</th><th>市值</th><th>股價</th><th>P/E</th>
        <th>1D%</th><th>1W%</th><th>1M%</th>
      </tr>{top10_rows}</table>""" if top10 else ""

    # ── 委託紀錄 ────────────────────────────────────────────────────────────
    orders_html = ""
    if orders:
        order_rows = ""
        for o in orders:
            side_zh = "買進" if o.get("side") == "buy" else "賣出"
            order_rows += f"""<tr>
              <td>{o.get('symbol','')}</td>
              <td>{side_zh}</td>
              <td>{int(o.get('qty',0))}</td>
              <td>{o.get('status','')}</td>
              <td>${o.get('filled_avg_price',0):,.2f}</td>
            </tr>"""
        orders_html = f"""
        <h3 style="color:#e06c1f">📋 今日委託紀錄</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%">
          <tr style="background:#555;color:#fff">
            <th>股票</th><th>方向</th><th>股數</th><th>狀態</th><th>成交均價</th>
          </tr>{order_rows}</table>"""

    # ── 關注清單 ────────────────────────────────────────────────────────────
    watchlist_html = ""
    for cat_name, stocks in watchlist.items():
        wrows = ""
        for s in stocks:
            c = "#2e9e5b" if (s.get("1d_pct") or 0) >= 0 else "#c0392b"
            wrows += f"""<tr>
              <td>{s.get('symbol','')}</td>
              <td>${s.get('price',0):,.2f}</td>
              <td style="color:{c}">{s.get('1d_pct','N/A')}%</td>
              <td>{s.get('1w_pct','N/A')}%</td>
              <td>{s.get('pe_ratio','N/A')}</td>
            </tr>"""
        watchlist_html += f"""
        <h4 style="color:#555">📌 {cat_name}</h4>
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse:collapse;width:100%">
          <tr style="background:#999;color:#fff">
            <th>股票</th><th>股價</th><th>1D%</th><th>1W%</th><th>P/E</th>
          </tr>{wrows}</table>"""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><title>AlpacaBot 日報</title></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;padding:20px;color:#333">

<div style="background:#e06c1f;color:#fff;padding:20px;border-radius:8px;text-align:center">
  <h1 style="margin:0">📊 AlpacaBot 每日報告</h1>
  <p style="margin:5px 0">{report_date} | {acct_name} ({acct_id})</p>
</div>

<div style="display:flex;gap:20px;margin:20px 0;flex-wrap:wrap">
  <div style="flex:1;background:#fff7f0;border:1px solid #e06c1f;border-radius:8px;padding:15px;text-align:center">
    <div style="font-size:14px;color:#888">💵 現金水位</div>
    <div style="font-size:24px;font-weight:bold">${report.get('cash',0):,.2f}</div>
  </div>
  <div style="flex:1;background:#fff7f0;border:1px solid #e06c1f;border-radius:8px;padding:15px;text-align:center">
    <div style="font-size:14px;color:#888">📈 帳戶淨值（NAV）</div>
    <div style="font-size:24px;font-weight:bold">${nav_cur:,.2f}</div>
    <div style="color:{chg_color};font-weight:bold">{chg_arrow} {abs(nav_chg or 0):.2f}%</div>
  </div>
  <div style="flex:1;background:#fff7f0;border:1px solid #e06c1f;border-radius:8px;padding:15px;text-align:center">
    <div style="font-size:14px;color:#888">📉 目前回撤</div>
    <div style="font-size:24px;font-weight:bold;color:#c0392b">{drawdown.get('current_pct',0):.2f}%</div>
    <div style="color:#888;font-size:12px">最大回撤：{drawdown.get('max_pct',0):.2f}%</div>
  </div>
  <div style="flex:1;background:#fff7f0;border:1px solid #e06c1f;border-radius:8px;padding:15px;text-align:center">
    <div style="font-size:14px;color:#888">🌐 基準比較</div>
    <div style="font-size:14px">NASDAQ：{benchmark.get('nasdaq_1d_pct','N/A')}%</div>
    <div style="font-size:14px">S&P500：{benchmark.get('sp500_1d_pct','N/A')}%</div>
  </div>
</div>

{holdings_html}
{orders_html}
{top10_html}
{watchlist_html if watchlist_html else ""}

<div style="margin-top:30px;padding:15px;background:#f5f5f5;border-radius:8px;font-size:12px;color:#888">
  ⚠️ <b>投資風險免責聲明</b><br>
  本報告所有內容（排名、績效、預測、通知）僅供資訊整理與研究參考，<b>不構成任何投資建議</b>。
  股票市場具有風險，過去績效不代表未來結果。投資前請自行評估風險。<br><br>
  AlpacaBot 自動交易系統 | 由 Python + Alpaca API 驅動
</div>
</body></html>"""


# ─── 對外介面 ─────────────────────────────────────────────────────────────────

class EmailSender:
    """Email 發送器（每個帳戶一個實例）"""

    def __init__(self, email: str, account_id: str):
        self.email      = email
        self.account_id = account_id

    def send_daily_report(self, report: dict) -> bool:
        """
        發送每日報告 Email

        建議於每日 06:00 AM（ET）呼叫
        """
        date_str = report.get("report_date", "")
        nav_cur  = report.get("nav", {}).get("current", 0)
        nav_chg  = report.get("nav", {}).get("change_pct", 0)
        arrow    = "▲" if (nav_chg or 0) >= 0 else "▼"

        subject  = (f"【AlpacaBot 日報】{date_str} | "
                    f"帳戶 {self.account_id} | "
                    f"NAV ${nav_cur:,.0f} {arrow}{abs(nav_chg or 0):.2f}%")
        html     = _render_daily_report_html(report)
        return send_email(self.email, subject, html)

    def send_trade_alert(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        order_id: str = "",
    ) -> bool:
        """即時交易通知（與 notifier.py 功能相同，方便單獨使用）"""
        from src.notifier import Notifier
        n = Notifier(self.email, self.account_id)
        return n.notify_trade(symbol, side, qty, price, order_id)
