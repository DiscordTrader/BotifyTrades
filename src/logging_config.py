"""
Logging configuration for QuantumPulse Discord Trading Bot
- Clean console output (signals, channels, balance only)
- Detailed logs saved to rotating files (max 10MB, keep 5 files)
- Log rotation on every restart with timestamp
"""

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# EST timezone
EST = ZoneInfo("America/New_York")

def get_app_directory():
    """Get the application directory - works for both script and frozen exe."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent.parent

# Create logs directory (minimal output for fast startup)
APP_DIR = get_app_directory()
LOGS_DIR = APP_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

# Log file paths
BOT_LOG_FILE = LOGS_DIR / 'bot.log'
TRADES_LOG_FILE = LOGS_DIR / 'trades.log'
ERRORS_LOG_FILE = LOGS_DIR / 'errors.log'

# Log rotation settings
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5  # Keep last 5 sessions


def rotate_logs_on_startup():
    """Rotate logs on every restart - archive with timestamp."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    for log_file in [BOT_LOG_FILE, TRADES_LOG_FILE, ERRORS_LOG_FILE]:
        if log_file.exists() and log_file.stat().st_size > 0:
            # Rename current log to timestamped archive
            archive_name = log_file.with_suffix(f'.{timestamp}.log')
            try:
                log_file.rename(archive_name)
            except:
                pass  # Skip if file is locked
    
    # Clean up old archives (keep last 5 per log type)
    for pattern in ['bot.*.log', 'trades.*.log', 'errors.*.log']:
        # Safe sort - handle files deleted between glob and stat
        def safe_mtime(f):
            try:
                return f.stat().st_mtime
            except (FileNotFoundError, OSError):
                return 0
        archives = sorted(LOGS_DIR.glob(pattern), key=safe_mtime, reverse=True)
        for old_archive in archives[BACKUP_COUNT:]:
            try:
                old_archive.unlink()
            except:
                pass


# Rotate logs on startup (fast, non-blocking)
rotate_logs_on_startup()


def _safe_str(msg):
    """Ensure string is safe for any output encoding (replace unencodable chars)."""
    if isinstance(msg, bytes):
        return msg.decode('utf-8', errors='replace')
    try:
        msg.encode('utf-8')
        return msg
    except (UnicodeEncodeError, UnicodeDecodeError):
        return msg.encode('ascii', errors='replace').decode('ascii')


class CleanConsoleFormatter(logging.Formatter):
    """Custom formatter for clean console output - trading signals, broker status, errors"""
    
    # STRICT WHITELIST - only these messages show in console
    CONSOLE_WHITELIST = [
        # Trading signals
        '[Signal]', '[BTO]', '[STC]', '[EXECUTE]', '[SIGNAL PARSED]',
        # Position/PNL
        '[Channel]', '[Balance]', '[Position]', '[P&L]', '[POSITION SIZE]',
        # Order execution
        '[ORDER]', '[FILLED]', '[CANCELLED]', '[QUEUE]',
        # Errors/Warnings
        '[ERROR]', '[CRITICAL]', '[WARNING]',
        # Broker initialization
        '[Webull]', '[WEBULL]', '[PAPER]', '[LIVE]', '[ASYNC]', '[Init]', '[Discord]',
        '[ALPACA]', '[TASTYTRADE]', '[ROBINHOOD]', '[IBKR]', '[SCHWAB]',
        '[DHANQ]', '[ZERODHA]', '[UPSTOX]', '[OPTIONS API]',
        # System status
        '[MAIN]', '[GUI]', '[STARTUP]', '[CONFIG]', '[LICENSE]',
        '[WORKER]', '[SYNC]', '[DATABASE]', '[RISK]', '[TELEGRAM]',
        '[PAPER TRADE]', '[MULTI-BROKER]', '[ROUTER]', '[LIFECYCLE]',
        # Conditional orders
        '[CONDITIONAL]',
        # Order chaser
        '[ORDER_CHASER]',
        # Streaming / Data Hub
        '[WEBULL_STREAM]', '[WEBULL_HUB]', '[SCHWAB_STREAM]', '[SCHWAB_HUB]',
        # Token management / Hot-connect
        '[SCHWAB TOKEN]', '[SCHWAB HOT-CONNECT]',
        # SOD Balance Cache
        '[SOD]',
        # EMA Candlestick Risk Engine
        '[EMA]',
        # Unified Price Hub
        '[UPH]',
        # IBKR Data Hub
        '[IBKR_HUB]',
        # Debug (when enabled)
        '[DEBUG]', '[API]', '[ROUTE]'
    ]
    
    def format(self, record):
        try:
            msg = _safe_str(record.getMessage())
        except Exception:
            msg = str(record.msg)
        
        # STRICT: Only show whitelisted messages in console
        if any(msg.startswith(prefix) for prefix in self.CONSOLE_WHITELIST):
            est_time = datetime.now(EST).strftime('%H:%M:%S')
            return f"[{est_time} EST] {msg}"
        
        # Everything else is suppressed from console (but goes to files)
        return None


class DetailedFileFormatter(logging.Formatter):
    """Formatter for detailed file logs with EST timestamps"""
    
    def format(self, record):
        try:
            est_time = datetime.now(EST).strftime('%Y-%m-%d %H:%M:%S')
            msg = _safe_str(record.getMessage())
            return f"{est_time} EST - {record.levelname} - {msg}"
        except Exception:
            return f"LOG_FORMAT_ERROR - {record.msg}"


def setup_logging():
    """Configure logging with clean console and detailed rotating file logs"""
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # ========================================
    # CONSOLE HANDLER (Debug mode enabled)
    # ========================================
    try:
        import io
        console_stream = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        console_handler = logging.StreamHandler(console_stream)
    except (AttributeError, Exception):
        console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(CleanConsoleFormatter())
    
    # Custom filter to suppress verbose messages
    class ConsoleFilter(logging.Filter):
        def filter(self, record):
            formatted = CleanConsoleFormatter().format(record)
            return formatted is not None
    
    console_handler.addFilter(ConsoleFilter())
    root_logger.addHandler(console_handler)
    
    # ========================================
    # BOT LOG FILE (All detailed logs)
    # ========================================
    bot_file_handler = RotatingFileHandler(
        BOT_LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    bot_file_handler.setLevel(logging.DEBUG)
    bot_file_handler.setFormatter(DetailedFileFormatter())
    root_logger.addHandler(bot_file_handler)
    
    # ========================================
    # TRADES LOG FILE (Trade-specific logs)
    # ========================================
    trades_file_handler = RotatingFileHandler(
        TRADES_LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    trades_file_handler.setLevel(logging.INFO)
    
    # Filter for trade-related messages only
    class TradeFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            return any(keyword in msg for keyword in ['[Signal]', '[BTO]', '[STC]', '[ORDER]', 
                                                       '[FILLED]', '[Position]', '[P&L]'])
    
    trades_file_handler.addFilter(TradeFilter())
    trades_file_handler.setFormatter(DetailedFileFormatter())
    root_logger.addHandler(trades_file_handler)
    
    # ========================================
    # ERROR LOG FILE (Errors and warnings only)
    # ========================================
    error_file_handler = RotatingFileHandler(
        ERRORS_LOG_FILE,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    error_file_handler.setLevel(logging.WARNING)
    error_file_handler.setFormatter(DetailedFileFormatter())
    root_logger.addHandler(error_file_handler)
    
    # ========================================
    # Suppress verbose third-party loggers (console + files)
    # ========================================
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
    logging.getLogger('discord.gateway').setLevel(logging.WARNING)
    logging.getLogger('discord.client').setLevel(logging.WARNING)
    logging.getLogger('discord.state').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)  # Suppress Flask HTTP logs
    logging.getLogger('flask').setLevel(logging.WARNING)   # Suppress Flask logs
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str = __name__):
    """Get a logger instance"""
    return logging.getLogger(name)


# Initialize logging when module is imported
logger = setup_logging()

# Export logger for external use
__all__ = ['logger', 'log_signal', 'log_execution', 'log_balance', 'log_channel', 
           'log_position', 'log_debug', 'log_error', 'log_warning', 'log_startup']


# Helper functions for clean console output
def log_signal(action: str, symbol: str, details: str = ""):
    """Log trading signal - shows in console"""
    logger.info(f"[Signal] {action} {symbol} {details}")


def log_execution(action: str, symbol: str, qty: int, price: float, status: str = ""):
    """Log order execution - shows in console"""
    logger.info(f"[EXECUTE] {action} {qty} {symbol} @ ${price} {status}")


def log_balance(buying_power: float, net_liq: float = None):
    """Log account balance - shows in console"""
    if net_liq:
        logger.info(f"[Balance] Buying Power: ${buying_power:.2f} | Net Liq: ${net_liq:.2f}")
    else:
        logger.info(f"[Balance] Buying Power: ${buying_power:.2f}")


def log_channel(channel_name: str, status: str):
    """Log channel status - shows in console"""
    logger.info(f"[Channel] {channel_name} - {status}")


def log_position(symbol: str, qty: int, pnl: float = None):
    """Log position update - shows in console"""
    if pnl is not None:
        logger.info(f"[Position] {symbol} x{qty} | P&L: ${pnl:.2f}")
    else:
        logger.info(f"[Position] {symbol} x{qty}")


def log_debug(message: str):
    """Log debug message - only goes to file, not console"""
    logger.debug(f"[DEBUG] {message}")


def log_error(message: str, exception: Exception = None):
    """Log error - shows in console and error log"""
    if exception:
        logger.error(f"[ERROR] {message}: {exception}", exc_info=True)
    else:
        logger.error(f"[ERROR] {message}")


def log_warning(message: str):
    """Log warning - shows in console"""
    logger.warning(f"[WARNING] {message}")


def log_startup(message: str):
    """Log startup message - shows in console"""
    logger.info(f"[Init] {message}")
