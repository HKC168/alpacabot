"""
account_loader.py
從 accounts/account_config.json 載入所有帳戶設定

使用方式：
    from src.account_loader import load_accounts, get_client
    accounts = load_accounts()
    client = get_client(accounts[0])
"""

import json
import os
from pathlib import Path
from src.alpaca_client import AccountConfig, AlpacaClient

# 預設設定檔路徑（可被測試覆寫）
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "accounts" / "account_config.json"


def load_accounts(config_path: Path = DEFAULT_CONFIG_PATH) -> list[AccountConfig]:
    """
    讀取 account_config.json，回傳所有帳戶設定列表

    每個帳戶的 API Key/Secret 從環境變數讀取（不存在此函式中）
    """
    if not config_path.exists():
        raise FileNotFoundError(f"帳戶設定檔不存在：{config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    accounts_raw = data.get("accounts", [])
    if not accounts_raw:
        raise ValueError("account_config.json 中沒有任何帳戶設定")

    accounts = []
    for a in accounts_raw:
        accounts.append(
            AccountConfig(
                id=a["id"],
                name=a["name"],
                endpoint=a["endpoint"],
                api_key_env=a["api_key_env"],
                secret_key_env=a["secret_key_env"],
                active_strategy=a["active_strategy"],
                email=a["email"],
                notification=a.get("notification", {}),
            )
        )
    return accounts


def get_client(account_cfg: AccountConfig) -> AlpacaClient:
    """用帳戶設定建立 AlpacaClient"""
    return AlpacaClient(account_cfg)


def load_all_clients(config_path: Path = DEFAULT_CONFIG_PATH) -> list[tuple[AccountConfig, AlpacaClient]]:
    """
    載入所有帳戶並建立對應的 AlpacaClient
    回傳 (AccountConfig, AlpacaClient) 的 tuple 列表
    """
    accounts = load_accounts(config_path)
    return [(cfg, AlpacaClient(cfg)) for cfg in accounts]
