"""
main.py
AlpacaBot 主程式入口（Phase 10）

用法：
  python src/main.py --mode trading       # 執行交易策略（開盤時使用）
  python src/main.py --mode report        # 生成日報 + 發送 Email
  python src/main.py --mode rebalance     # 檢查並執行再平衡
  python src/main.py --mode rebalance --force-rebalance  # 強制再平衡

流程（每個帳戶依序執行）：
  1. 載入帳戶設定
  2. 建立 Alpaca 客戶端
  3. 依帳戶綁定的策略執行操作
  4. 生成報告 / 發送 Email

⚠️ 本系統僅依使用者設定執行，不構成投資建議。
"""

import argparse
import logging
import sys
from pathlib import Path

# 確保從專案根目錄執行
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.account_loader import load_accounts, get_client
from src.email_sender import EmailSender
from src.notifier import Notifier
from src.order_executor import OrderExecutor
from src.rebalancer import Rebalancer, should_rebalance, load_state, save_state
from src.report_generator import generate_daily_report, save_report
from src.strategy_engine import load_strategy, get_target_positions

# ─── 日誌設定 ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alpacabot.main")


# ─── 模式執行函式 ─────────────────────────────────────────────────────────────

def run_trading(account_cfg, client):
    """
    執行交易策略：
    1. 取得目前持倉
    2. 依策略計算目標持倉
    3. 執行差額買賣
    """
    logger.info("═══ [TRADING] 帳戶 %s ═══", account_cfg.id)
    try:
        account_info = client.get_account_info()
        positions    = client.get_positions()
        strategy     = load_strategy(account_cfg.active_strategy)
        target       = get_target_positions(account_info["equity"], strategy)

        current  = {p["symbol"]: int(p["qty"]) for p in positions}
        notifier = Notifier(account_cfg.email, account_cfg.id)
        executor = OrderExecutor(client, notifier)
        result   = executor.execute_rebalance(target, positions, account_info)

        logger.info("[%s] 買進 %d 筆，賣出 %d 筆，跳過 %d 筆",
                    account_cfg.id, result.total_bought, result.total_sold,
                    len(result.orders_skipped))

        # 更新現金狀態
        updated_info = client.get_account_info()
        state = load_state(account_cfg.id)
        state["last_cash"] = updated_info["cash"]
        state["last_nav"]  = updated_info["equity"]
        if not state.get("peak_nav"):
            state["peak_nav"] = updated_info["equity"]
        save_state(account_cfg.id, state)

        return result
    except Exception as e:
        logger.error("[%s] 交易執行失敗：%s", account_cfg.id, e)
        try:
            Notifier(account_cfg.email, account_cfg.id).notify_error(str(e))
        except Exception:
            pass
        return None


def run_report(account_cfg, client):
    """生成日報並發送 Email"""
    logger.info("═══ [REPORT] 帳戶 %s ═══", account_cfg.id)
    try:
        report = generate_daily_report(account_cfg, client)
        path   = save_report(report)
        logger.info("[%s] 報告儲存至：%s", account_cfg.id, path)

        sender = EmailSender(account_cfg.email, account_cfg.id)
        ok     = sender.send_daily_report(report)
        if ok:
            logger.info("[%s] 日報 Email 已發送至 %s", account_cfg.id, account_cfg.email)
        else:
            logger.warning("[%s] Email 發送失敗（SMTP 未設定？）", account_cfg.id)
        return report
    except Exception as e:
        logger.error("[%s] 日報生成失敗：%s", account_cfg.id, e)
        return None


def run_rebalance(account_cfg, client, force: bool = False):
    """執行再平衡"""
    logger.info("═══ [REBALANCE] 帳戶 %s ═══", account_cfg.id)
    try:
        r = Rebalancer(client, account_cfg)
        result = r.run(force=force)
        if result.triggered:
            logger.info("[%s] 再平衡完成（原因：%s）", account_cfg.id, result.reason)
        else:
            logger.info("[%s] 不需再平衡", account_cfg.id)
        return result
    except Exception as e:
        logger.error("[%s] 再平衡失敗：%s", account_cfg.id, e)
        return None


# ─── 主程式 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AlpacaBot — 全自動美股投資系統",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模式說明：
  trading      開盤時執行，依策略下單
  report       收盤後執行，生成日報並發送 Email
  rebalance    再平衡檢查（每月初自動觸發，或加 --force-rebalance）

⚠️ 本系統所有操作僅供研究用途，不構成投資建議。
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["trading", "report", "rebalance"],
        default="report",
        help="執行模式",
    )
    parser.add_argument(
        "--force-rebalance",
        action="store_true",
        help="強制執行再平衡（忽略觸發條件）",
    )
    parser.add_argument(
        "--account",
        default=None,
        help="只執行指定帳戶 ID（不指定則執行所有帳戶）",
    )
    args = parser.parse_args()

    logger.info("╔══════════════════════════════════════╗")
    logger.info("║  AlpacaBot 啟動  mode=%s           ║", args.mode)
    logger.info("╚══════════════════════════════════════╝")

    # 載入所有帳戶
    try:
        accounts = load_accounts()
    except Exception as e:
        logger.error("無法載入帳戶設定：%s", e)
        sys.exit(1)

    if args.account:
        accounts = [a for a in accounts if a.id == args.account]
        if not accounts:
            logger.error("找不到帳戶：%s", args.account)
            sys.exit(1)

    logger.info("共載入 %d 個帳戶", len(accounts))

    # 逐帳戶執行
    for account_cfg in accounts:
        logger.info("▶ 帳戶：%s（策略：%s）", account_cfg.id, account_cfg.active_strategy)
        try:
            client = get_client(account_cfg)
        except Exception as e:
            logger.error("帳戶 %s 連線失敗：%s", account_cfg.id, e)
            continue

        if args.mode == "trading":
            run_trading(account_cfg, client)
        elif args.mode == "report":
            run_report(account_cfg, client)
        elif args.mode == "rebalance":
            run_rebalance(account_cfg, client, force=args.force_rebalance)

    logger.info("AlpacaBot 執行完成")


if __name__ == "__main__":
    main()
