"""
tests/test_email_sender.py — Phase 8 Email 通知測試
執行：pytest tests/test_email_sender.py -v -m "not live"
"""

from unittest.mock import patch, MagicMock
import pytest

from src.email_sender import (
    send_email, _render_daily_report_html, EmailSender,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_report():
    return {
        "report_date":  "2026-05-24",
        "account_id":   "PA3CVCWGFPAM",
        "account_name": "Han Paper Account",
        "nav":          {"current": 102000.0, "previous_day": 100000.0, "change_pct": 2.0},
        "cash":         80000.0,
        "equity":       102000.0,
        "buying_power": 200000.0,
        "drawdown":     {"current_pct": 0.0, "max_pct": 0.0, "peak_nav": 102000.0},
        "benchmark":    {"nasdaq_1d_pct": 0.5, "sp500_1d_pct": 0.3},
        "holdings": [
            {"symbol": "AAPL", "qty": 10.0, "market_value": 2000.0,
             "avg_cost": 190.0, "current_price": 200.0,
             "unrealized_pl": 100.0, "unrealized_plpc": 0.05}
        ],
        "top10_today": [
            {"rank": 1, "symbol": "AAPL", "market_cap": 3e12, "price": 200.0,
             "pe_ratio": 28.5, "1d_pct": 1.2, "1w_pct": 3.5, "1m_pct": 8.1,
             "name": "Apple Inc."}
        ],
        "orders_today": [],
        "watchlist":    {},
        "prediction_tomorrow": [],
        "disclaimer":   "⚠️ 本報告僅供參考",
    }

@pytest.fixture
def sender():
    return EmailSender("test@test.com", "PA3CVCWGFPAM")


# ─── Test 1: HTML 模板渲染 ────────────────────────────────────────────────────

class TestEmailHtmlRender:
    def test_html_contains_account_id(self, sample_report):
        """HTML 應含帳戶 ID"""
        html = _render_daily_report_html(sample_report)
        assert "PA3CVCWGFPAM" in html

    def test_html_contains_nav(self, sample_report):
        """HTML 應含 NAV 金額"""
        html = _render_daily_report_html(sample_report)
        assert "102,000" in html

    def test_html_contains_disclaimer(self, sample_report):
        """HTML 必須含免責聲明"""
        html = _render_daily_report_html(sample_report)
        assert "不構成任何投資建議" in html

    def test_html_contains_top10_header(self, sample_report):
        """HTML 含 Top10 標題（含研究參考警語）"""
        html = _render_daily_report_html(sample_report)
        assert "Top 10" in html

    def test_html_valid_structure(self, sample_report):
        """HTML 有基本結構（html、body 標籤）"""
        html = _render_daily_report_html(sample_report)
        assert "<html" in html
        assert "<body" in html
        assert "</html>" in html

    def test_html_contains_aapl(self, sample_report):
        """HTML 含持倉股票 AAPL"""
        html = _render_daily_report_html(sample_report)
        assert "AAPL" in html


# ─── Test 2: 發送日報 ────────────────────────────────────────────────────────

class TestSendDailyReport:
    def test_send_daily_report_calls_smtp(self, sender, sample_report):
        """send_daily_report 應呼叫 SMTP 發送"""
        with patch("src.email_sender.send_email", return_value=True) as mock_send:
            result = sender.send_daily_report(sample_report)
        mock_send.assert_called_once()
        assert result is True

    def test_subject_contains_account_id(self, sender, sample_report):
        """郵件主旨應含帳戶 ID"""
        captured_subject = []

        def capture_email(to, subject, html):
            captured_subject.append(subject)
            return True

        with patch("src.email_sender.send_email", side_effect=capture_email):
            sender.send_daily_report(sample_report)

        assert "PA3CVCWGFPAM" in captured_subject[0]

    def test_smtp_not_configured_returns_false(self, sender, sample_report, monkeypatch):
        """SMTP 未設定時回傳 False，不拋出例外"""
        monkeypatch.setenv("SMTP_USER",     "")
        monkeypatch.setenv("SMTP_PASSWORD", "")
        result = sender.send_daily_report(sample_report)
        assert result is False


# ─── Test 3: 即時交易通知 ────────────────────────────────────────────────────

class TestTradeAlertEmail:
    def test_trade_alert_calls_notifier(self, sender):
        """trade_alert 應呼叫 notifier.notify_trade"""
        with patch("src.notifier.Notifier.notify_trade", return_value=True) as mock_notify:
            result = sender.send_trade_alert("AAPL", "buy", 10, 195.0, "ORD-001")
        mock_notify.assert_called_once()
        assert result is True


# ─── Test 4: 多帳戶各自收到 Email ────────────────────────────────────────────

class TestMultiAccountEmail:
    def test_each_account_sends_to_own_email(self, sample_report):
        """每個帳戶應發送至各自 email"""
        emails_sent = []

        def capture(to, subject, html):
            emails_sent.append(to)
            return True

        senders = [
            EmailSender("user1@test.com", "ACCT001"),
            EmailSender("user2@test.com", "ACCT002"),
        ]
        with patch("src.email_sender.send_email", side_effect=capture):
            for s in senders:
                s.send_daily_report(sample_report)

        assert "user1@test.com" in emails_sent
        assert "user2@test.com" in emails_sent


# ─── Test 5: 免責聲明 ────────────────────────────────────────────────────────

class TestDisclaimerIncluded:
    def test_html_has_risk_disclaimer(self, sample_report):
        """HTML 必須包含風險免責聲明"""
        html = _render_daily_report_html(sample_report)
        keywords = ["投資風險", "不構成任何投資建議", "過去績效不代表未來結果"]
        for kw in keywords:
            assert kw in html, f"缺少免責聲明關鍵字：{kw}"
