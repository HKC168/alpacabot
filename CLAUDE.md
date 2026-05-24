# AlpacaBot — 專案記憶文件

> 供 AI 助理或新開發者快速了解本專案。每次重大變更後請更新此文件。

## 專案目標

全自動美股投資管理系統，整合 Alpaca Paper/Live API，功能涵蓋：
- 多帳戶管理，每帳戶獨立綁定一套 JSON 交易策略
- 每日自動選股（NASDAQ Top10）、下單、再平衡
- Streamlit 視覺化儀錶板
- 每日 06:00 AM（ET）Email 日報
- GitHub Actions 驅動全自動化流程

## 目前進度

| Phase | 狀態 | 說明 |
|-------|------|------|
| Phase 1：基礎架構 | ✅ 完成 | Alpaca Client、多帳戶載入、全部測試通過 |
| Phase 2：市場資料 | ✅ 完成 | Top10、P/E、報酬率、yfinance |
| Phase 3：策略引擎 | ✅ 完成 | JSON 策略載入、驗證、整體權重計算 |
| Phase 4：下單執行 | ✅ 完成 | 防重複下單、資金不足跳過、通知 |
| Phase 5：再平衡   | ✅ 完成 | 月首交易日、新資金入帳觸發 |
| Phase 6：日報生成 | ✅ 完成 | JSON Model + HTML View，NAV 歷史 |
| Phase 7：Dashboard | ✅ 完成 | Streamlit，五分頁，圖表 |
| Phase 8：Email 通知 | ✅ 完成 | SMTP，日報 + 交易提醒 |
| Phase 9：GitHub Actions | ✅ 完成 | 自動交易/報告/Email 流程 |
| Phase 10：整合測試 | ✅ 完成 | 146 個 Mock 測試全數通過 |
| **雲端 Dashboard** | ✅ 完成 | 不依賴本地電腦，支援 Streamlit Cloud |

## 目錄結構

```
alpacabot/
├── .github/workflows/daily_trading.yml      # GitHub Actions 主工作流
├── .streamlit/
│   ├── config.toml                          # Streamlit 主題設定
│   └── secrets.toml.example                 # Streamlit Secrets 模板（勿 commit 真實版）
├── accounts/account_config.json             # 多帳戶設定（不含金鑰）
├── strategies/*.json                        # 交易策略（新增策略只加 JSON）
├── reports/model/                           # 日報 JSON 資料
├── reports/history/                         # 歷史報告存檔
├── src/
│   ├── alpaca_client.py                     # Alpaca API 封裝（核心）
│   ├── account_loader.py                   # 多帳戶載入器
│   ├── market_data.py                      # 市場資料（yfinance）
│   ├── strategy_engine.py                  # 策略引擎（JSON 驅動）
│   ├── order_executor.py                   # 下單執行
│   ├── rebalancer.py                       # 再平衡引擎
│   ├── report_generator.py                 # 日報生成（JSON Model）
│   └── email_sender.py                     # Email 通知（HTML View）
├── dashboard/
│   ├── app.py                              # Streamlit 儀錶板（雲端版）
│   └── data_layer.py                       # 雲端資料抽象層（⭐ 關鍵）
└── tests/                                  # 全部測試（146 個 Mock）
```

## 核心設計原則

1. **策略 = JSON**：新增交易策略只需在 `strategies/` 加一個 `.json`，不需改 Python
2. **報告 Model/View 分離**：JSON 存資料（Model），Email/Dashboard 各自讀取呈現（View）
3. **金鑰全從環境變數**：`ALPACA_KEY_<ACCOUNT_ID>`、`ALPACA_SECRET_<ACCOUNT_ID>`，永不寫入程式碼
4. **多帳戶獨立**：每帳戶同一時間只綁定一個策略，可隨時切換
5. **測試先行**：每個 Phase 測試 100% 通過才開發下一段
6. **雲端優先**：Dashboard 不依賴本地環境，資料自動降級（Live → Cached → N/A）

## 重要環境變數

| 變數名稱 | 說明 |
|---------|------|
| `ALPACA_KEY_<ACCOUNT_ID>` | Alpaca API Key |
| `ALPACA_SECRET_<ACCOUNT_ID>` | Alpaca Secret Key |
| `SMTP_HOST` | Email 伺服器（e.g. smtp.gmail.com）|
| `SMTP_PORT` | Email Port（e.g. 587）|
| `SMTP_USER` | Email 帳號 |
| `SMTP_PASSWORD` | Email 應用程式密碼 |

## 執行指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 執行所有 Mock 測試
pytest tests/ -v -m "not live"

# 執行真實 API 測試（需要環境變數）
pytest tests/ -v -m live

# 啟動 Dashboard（本地）
# 先複製金鑰設定：cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# 再填入真實金鑰，然後：
streamlit run dashboard/app.py

# 手動執行交易流程
python src/main.py --mode trading

# 手動產生日報
python src/main.py --mode report
```

## 雲端 Dashboard 部署（Streamlit Cloud）

1. Push 到 GitHub（`secrets.toml` 已在 `.gitignore` 中）
2. 前往 https://share.streamlit.io → "New app"
3. 選擇 `HKC168/alpacabot`、Branch `main`、Main file `dashboard/app.py`
4. 點 "Advanced settings" → "Secrets"，貼入 `.streamlit/secrets.toml.example` 的內容（填入真實金鑰）
5. Deploy — 完成後 Dashboard 從任何地方皆可存取

## Dashboard 資料流（data_layer.py）

```
get_full_dashboard_data(account_id)
    ↓
    fetch_account_info()  →  build_alpaca_client()  →  Alpaca API（即時）
                          ↘  _load_latest_report_raw()  →  reports/ 目錄（快取）
    fetch_positions()     同上降級邏輯
    fetch_orders_today()  同上降級邏輯
    get_latest_report()   →  reports/ 目錄
    get_nav_history()     →  reports/nav_history/

憑證取得優先順序：
  Streamlit Secrets（st.secrets）→ account_config.json + 環境變數
```

## 帳戶資訊

- 帳戶 ID：PA3CVCWGFPAM
- 類型：Paper Trading
- Endpoint：https://paper-api.alpaca.markets
- 目前現金：$100,000 USD

## 策略規格（JSON Schema 重點）

```json
{
  "strategy_id": "...",
  "universe": "NASDAQ",
  "selection": { "method": "market_cap_top_n", "n": 10 },
  "allocation": { "type": "equal_weight", "per_position_pct": 10, "whole_shares_only": true },
  "rebalance": { "monthly": true, "on_new_deposit": true }
}
```

## 免責聲明

本系統所有輸出內容（排名、績效、預測、通知）**僅供資訊整理與研究參考，不構成任何投資建議**。
