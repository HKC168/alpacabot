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
| Phase 2：市場資料 | ⏳ 待開發 | Top10、P/E、報酬率 |
| Phase 3：策略引擎 | ⏳ 待開發 | JSON 策略載入 |
| Phase 4～10 | ⏳ 待開發 | 見 ALPACA_PROJECT_PLAN.md |

## 目錄結構

```
alpacabot/
├── .github/workflows/daily_trading.yml  # GitHub Actions 主工作流
├── accounts/account_config.json         # 多帳戶設定（不含金鑰）
├── strategies/*.json                    # 交易策略（新增策略只加 JSON）
├── reports/model/                       # 日報 JSON 資料
├── reports/history/                     # 歷史報告存檔
├── src/
│   ├── alpaca_client.py                 # Alpaca API 封裝（核心）
│   ├── account_loader.py               # 多帳戶載入器
│   ├── market_data.py                  # 市場資料（Phase 2）
│   ├── strategy_engine.py              # 策略引擎（Phase 3）
│   ├── order_executor.py               # 下單執行（Phase 4）
│   ├── rebalancer.py                   # 再平衡引擎（Phase 5）
│   ├── report_generator.py             # 日報生成（Phase 6）
│   └── email_sender.py                 # Email 通知（Phase 8）
├── dashboard/app.py                    # Streamlit Dashboard（Phase 7）
└── tests/                              # 每個 Phase 的測試案例
```

## 核心設計原則

1. **策略 = JSON**：新增交易策略只需在 `strategies/` 加一個 `.json`，不需改 Python
2. **報告 Model/View 分離**：JSON 存資料（Model），Email/Dashboard 各自讀取呈現（View）
3. **金鑰全從環境變數**：`ALPACA_KEY_<ACCOUNT_ID>`、`ALPACA_SECRET_<ACCOUNT_ID>`，永不寫入程式碼
4. **多帳戶獨立**：每帳戶同一時間只綁定一個策略，可隨時切換
5. **測試先行**：每個 Phase 測試 100% 通過才開發下一段

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

# 啟動 Dashboard（Phase 7 後可用）
streamlit run dashboard/app.py

# 手動執行交易流程
python src/main.py --mode trading

# 手動產生日報
python src/main.py --mode report
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
