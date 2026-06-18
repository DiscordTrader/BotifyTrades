"""Debug script: shows exact raw JSON from Webull Official balance API"""
import sys, io, os, asyncio, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')

from gui_app.broker_credentials_service import get_webull_official_credentials
from src.brokers.webull_official.client import WebullClient
from src.brokers.webull_official.config import WebullConfig
from pathlib import Path


async def main():
    creds = get_webull_official_credentials()
    app_key = creds.get('app_key', '')
    app_secret = creds.get('app_secret', '')
    if not app_key or not app_secret:
        print("ERROR: Missing app_key or app_secret")
        return

    cfg = WebullConfig(app_key=app_key, app_secret=app_secret)
    client = WebullClient(cfg, token_file=Path('webull_official_token.json'))
    await client.start()

    try:
        token_data = json.loads(Path('webull_official_token.json').read_text())
        client.set_access_token(token_data.get('token', ''))

        print("\n=== LIST ACCOUNTS ===")
        accounts_raw = await client.get("/openapi/account/list")
        print(json.dumps(accounts_raw, indent=2))

        # Pick first account
        accs = accounts_raw if isinstance(accounts_raw, list) else accounts_raw.get('accounts', accounts_raw.get('data', []))
        if not accs:
            print("No accounts found")
            return
        account_id = accs[0].get('account_id', '')
        print(f"\nUsing account_id: {account_id}")

        print("\n=== RAW BALANCE RESPONSE ===")
        balance_raw = await client.get("/openapi/assets/balance", params={"account_id": account_id})
        print(json.dumps(balance_raw, indent=2))

        print("\n=== KEY FIELDS ===")
        # Top level
        for key in ['total_cash_balance', 'total_market_value', 'total_net_liquidation_value',
                    'total_unrealized_profit_loss', 'total_day_profit_loss', 'day_trades_left']:
            print(f"  {key}: {balance_raw.get(key, 'MISSING')}")

        # Currency assets
        currency_assets = balance_raw.get('account_currency_assets', [])
        print(f"\n  account_currency_assets count: {len(currency_assets)}")
        if currency_assets:
            print(f"  account_currency_assets[0] keys: {list(currency_assets[0].keys())}")
            for key in ['buying_power', 'settled_cash', 'unsettled_cash', 'option_buying_power',
                        'day_buying_power', 'overnight_buying_power', 'cash_balance']:
                print(f"    {key}: {currency_assets[0].get(key, 'MISSING')}")

    finally:
        await client.close()


asyncio.run(main())
