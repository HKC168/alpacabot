"""
notifier.py
即時交易通知模組（Phase 4）

有交易成交時，立即發送 Email 通知。
若 SMTP 未設定，僅記錄 log，不拋出例外（避免通知失敗中斷主流程）。
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _get_smtp_config() -> dict:
    return {
        "host":     os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port":     int(os.environ.get("SMTP_PORT", "587")),
        "user":     os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
    }


def _send_email(to: str, subject: str, html_body: str) -> bool:
    """發送 HTML Email，失敗時回傳 False 並記錄 log"""
    cfg = _get_smtp_config()
    if not cfg["user"] or not cfg["password"]:
        logger.warning("SMTP 未設定，跳過發送：%s", subject)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["user"]
        msg["To"]      = to
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["user"], to, msg.as_string())
        logger.info("Email 已發送：%s → %s", subject, to)
        return True
    except Exception as e:
        logger.error("Email 發送失敗：%s", e)
        return False


class Notifier:
    """交易即時通知器"""

    def __init__(self, email: str, account_id: str):
        self.email      = email
        self.account_id = account_id

    def notify_trade(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        order_id: str = "",
    ) -> bool:
        """
        交易成交通知

        側（side）：buy（買進）或 sell（賣出）
        """
        side_zh  = "買進 📈" if side == "buy" else "賣出 📉"
        total    = qty * price if price else 0
        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject  = f"【AlpacaBot 交易通知】{symbol} {side_zh} {qty} 股"
        body = f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
<h2 style="color:#e06c1f">AlpacaBot 交易通知</h2>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
  <tr><td><b>帳戶</b></td><td>{self.account_id}</td></tr>
  <tr><td><b>股票</b></td><td>{symbol}</td></tr>
  <tr><td><b>操作</b></td><td>{side_zh}</td></tr>
  <tr><td><b>股數</b></td><td>{qty} 股</td></tr>
  <tr><td><b>成交價</b></td><td>${price:,.2f}</td></tr>
  <tr><td><b>成交金額</b></td><td>${total:,.2f}</td></tr>
  <tr><td><b>時間</b></td><td>{now}</td></tr>
  <tr><td><b>委託 ID</b></td><td>{order_id}</td></tr>
</table>
<p style="color:#888;font-size:12px;margin-top:20px">
⚠️ 本通知僅供資訊記錄，不構成投資建議。<br>
AlpacaBot 自動交易系統
</p>
</body></html>"""
        logger.info("交易通知：%s %s %s %d 股 @ $%.2f", self.account_id, side_zh, symbol, qty, price)
        return _send_email(self.email, subject, body)

    def notify_error(self, message: str) -> bool:
        """系統錯誤通知"""
        subject = f"【AlpacaBot 錯誤】帳戶 {self.account_id}"
        body = f"""
<html><body style="font-family:Arial,sans-serif">
<h2 style="color:red">AlpacaBot 系統錯誤</h2>
<p><b>帳戶：</b>{self.account_id}</p>
<p><b>錯誤訊息：</b>{message}</p>
<p><b>時間：</b>{datetime.now()}</p>
</body></html>"""
        return _send_email(self.email, subject, body)
