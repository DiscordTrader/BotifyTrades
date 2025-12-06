# Discord Trading Bot for Webull

## Overview
This project is a Discord self-bot designed to automate stock and options trading on the Webull brokerage platform. It monitors specified Discord channels for trading signals (BTO/STC) and executes trades, incorporating comprehensive risk management features like profit targets, stop losses, and trailing stops. The bot is cross-platform compatible, supports flexible signal parsing, and prioritizes secure credential management. The overarching goal is to provide an automated, reliable, and secure tool for executing trading strategies derived from Discord signals.

## User Preferences
- **Security**: Always use environment variables (Replit Secrets) for credentials
- **Testing**: Test with paper_trade = true before enabling live trading
- **Monitoring**: Review console logs regularly for trade execution
- **Channel filtering**: Only process signals from designated channels
- **Deployment**: Prefer local machine or cloud VPS for 24/7 operation

## System Architecture

### UI/UX Decisions
The bot operates as a backend service with no direct UI. Configuration is managed via `config.ini` and environment variables. Setup is streamlined with an interactive wizard for credential configuration, and an optional Windows EXE provides a non-technical deployment option. Console output is designed to be clean, with silent filtering of messages from unmonitored channels.

### Technical Implementations
- **Core Components**: Utilizes `discord.py-self` for Discord integration and the `webull` Python package for brokerage interaction.
- **Async Processing**: Employs a queue-based system for reliable order execution.
- **Signal Parsing**: Regex-based pattern matching handles various BTO/STC signal formats, including optional symbols and case-insensitivity.
- **Risk Management**: Implements automated profit targets (20%), stop losses (10%), and trailing stops (5%), with position monitoring every 30 seconds.
- **Credential Management**: Environment variables (Replit Secrets) are the primary method for secure credential storage. On local deployments, an interactive setup wizard encrypts and stores credentials.
- **Cross-Platform Compatibility**: Designed to run seamlessly on Replit, local Windows/Mac/Linux machines, and Cloud VPS environments.
- **Options Handling**: Supports LEAPS and accurately calculates option costs (1 contract = 100 shares), displaying full metadata (strike/expiry/direction).
- **Auto-Quantity**: When quantity is not specified in a signal, the bot calculates position size based on a configurable max position size ($200 by default).

### Feature Specifications
- **Live Trading**: Enabled by default (`paper_trade = false`).
- **Token-based Authentication**: Fast Webull login using saved access and refresh tokens.
- **Flexible Signal Formats**: Supports `$` signs, optional `@` symbols, and case-insensitive option types.
- **Automated Risk Management**: Configurable profit targets, stop losses, and trailing stops.
- **Position Monitoring**: Tracks open positions and applies risk management rules.
- **Secure Deployment**: Credentials managed via environment variables (Replit Secrets) or encrypted local storage.
- **Self-Message Support**: Can process signals originating from the bot's own Discord account (e.g., for testing).

### System Design Choices
- **Modularity**: Code is organized into `src/` for core logic and separate files for setup (`setup_wizard.py`).
- **Configuration**: `config.ini` manages operational settings like channel IDs, max position size, and trading mode.
- **Deployment Flexibility**: Supports multiple deployment options including Replit, local machines (with specific setup guides and scripts), and cloud VPS.
- **Error Handling & Logging**: Comprehensive logging for debugging and monitoring trade execution.

## External Dependencies
- **Python**: Version 3.11+
- **discord.py-self**: Version 2.0.1+ (Discord API interaction)
- **webull**: Version 0.6.1+ (Webull brokerage API interaction)
- **requests**: Version 2.28.0+ (HTTP requests)