# India Bot - Trading Bot for Indian Markets

Standalone trading bot for Indian markets (NSE/BSE/MCX) extracted from BotifyTrades.

## Supported Brokers

- **Upstox** - OAuth2 API with auto token refresh
- **Zerodha (Kite)** - Kite Connect API
- **DhanQ** - DhanHQ API

## Features

- Real-time signal processing from Telegram
- Conditional orders with price triggers
- Position sizing in lots (auto-multiplied by lot size)
- Web control panel for monitoring
- Order queue with AMO support for Upstox

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure broker credentials via web panel or database

3. Run the bot:
   ```bash
   python main.py
   ```

4. Access web panel at http://localhost:5000

## Directory Structure

```
india_bot/
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── src/
│   ├── brokers/           # Broker implementations
│   │   ├── upstox_broker.py
│   │   ├── zerodha_broker.py
│   │   └── dhanq_broker.py
│   ├── services/          # Core services
│   │   ├── conditional_orders/
│   │   │   ├── india_service.py
│   │   │   └── base.py
│   │   ├── expiry_resolver.py
│   │   └── contract_master.py
│   ├── adapters/          # Execution adapters
│   │   └── india_execution_adapter.py
│   └── broker_interface.py # Base broker interface
├── gui_app/
│   ├── app.py             # Flask application
│   ├── database.py        # SQLite database
│   ├── templates/         # HTML templates
│   └── static/            # CSS/JS assets
```

## Configuration

Broker credentials are stored in SQLite database (`india_bot.db`).

### Upstox
- API Key
- API Secret
- Access Token
- Redirect URI

### Zerodha
- API Key
- API Secret
- User ID
- TOTP Secret

### DhanQ
- Client ID
- Access Token

## Migration from Main Project

This directory is designed to be copied as-is to a separate Replit project.

1. Copy entire `india_bot/` directory
2. Install dependencies: `pip install -r requirements.txt`
3. Run: `python main.py`
4. Configure brokers via web panel

## Notes

- All trades are LIVE - there is no paper trading mode for Indian brokers
- Lot sizes are fetched from broker APIs automatically
- Position sizes in channel settings are treated as number of lots
