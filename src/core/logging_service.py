"""
BotifyTrades Centralized Logging Service
Industry-standard log rotation with TimedRotatingFileHandler
"""
import os
import sys
import gzip
import shutil
import logging
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class CompressedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler that compresses old log files with gzip.
    Rotates at midnight, keeps logs for configurable days.
    """
    
    def __init__(self, filename, when='midnight', interval=1, backupCount=14,
                 encoding='utf-8', delay=False, compress_after_days=7):
        super().__init__(filename, when=when, interval=interval,
                        backupCount=backupCount, encoding=encoding, delay=delay)
        self.compress_after_days = compress_after_days
    
    def doRollover(self):
        super().doRollover()
        self._compress_old_logs()
        self._cleanup_old_logs()
    
    def _compress_old_logs(self):
        """Compress log files older than compress_after_days"""
        log_dir = os.path.dirname(self.baseFilename)
        base_name = os.path.basename(self.baseFilename)
        compress_threshold = datetime.now() - timedelta(days=self.compress_after_days)
        
        for filename in os.listdir(log_dir):
            if filename.startswith(base_name) and not filename.endswith('.gz'):
                file_path = os.path.join(log_dir, filename)
                if file_path == self.baseFilename:
                    continue
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_mtime < compress_threshold:
                        with open(file_path, 'rb') as f_in:
                            with gzip.open(f'{file_path}.gz', 'wb') as f_out:
                                shutil.copyfileobj(f_in, f_out)
                        os.remove(file_path)
                except Exception:
                    pass
    
    def _cleanup_old_logs(self):
        """Remove logs beyond retention period"""
        log_dir = os.path.dirname(self.baseFilename)
        base_name = os.path.basename(self.baseFilename)
        retention_threshold = datetime.now() - timedelta(days=self.backupCount + 7)
        
        for filename in os.listdir(log_dir):
            if filename.startswith(base_name):
                file_path = os.path.join(log_dir, filename)
                if file_path == self.baseFilename:
                    continue
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_mtime < retention_threshold:
                        os.remove(file_path)
                except Exception:
                    pass


def get_log_directory() -> Path:
    """
    Get the appropriate log directory based on platform and execution context.
    - Windows: %LOCALAPPDATA%/BotifyTrades/Logs
    - Linux/Mac: ~/.local/share/BotifyTrades/Logs
    - Development: ./logs in working directory
    """
    if getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            base_dir = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
            log_dir = base_dir / 'BotifyTrades' / 'Logs'
        else:
            log_dir = Path.home() / '.local' / 'share' / 'BotifyTrades' / 'Logs'
    else:
        log_dir = Path.cwd() / 'logs'
    
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class LoggingService:
    """
    Centralized logging service with:
    - TimedRotatingFileHandler (midnight rollover, 14-day retention)
    - Optional debug file with size-based rotation
    - Console output (when not running as service)
    - Compressed archives for old logs
    """
    
    _instance: Optional['LoggingService'] = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.log_dir = get_log_directory()
        self.loggers = {}
        self.main_handler: Optional[CompressedTimedRotatingFileHandler] = None
        self.debug_handler: Optional[RotatingFileHandler] = None
        self.console_handler: Optional[logging.StreamHandler] = None
        
        self._setup_logging()
        LoggingService._initialized = True
    
    def _setup_logging(self):
        """Configure all logging handlers"""
        log_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        main_log_file = self.log_dir / 'botifytrades.log'
        self.main_handler = CompressedTimedRotatingFileHandler(
            filename=str(main_log_file),
            when='midnight',
            interval=1,
            backupCount=14,
            encoding='utf-8',
            compress_after_days=7
        )
        self.main_handler.setFormatter(log_format)
        self.main_handler.setLevel(logging.INFO)
        
        debug_log_file = self.log_dir / 'debug.log'
        self.debug_handler = RotatingFileHandler(
            filename=str(debug_log_file),
            maxBytes=50 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8'
        )
        debug_format = logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-20s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.debug_handler.setFormatter(debug_format)
        self.debug_handler.setLevel(logging.DEBUG)
        
        self.console_handler = logging.StreamHandler(sys.stdout)
        console_format = logging.Formatter('[%(name)s] %(message)s')
        self.console_handler.setFormatter(console_format)
        self.console_handler.setLevel(logging.INFO)
    
    def get_logger(self, name: str, include_console: bool = True) -> logging.Logger:
        """
        Get or create a logger with the specified name.
        
        Args:
            name: Logger name (e.g., 'Discord', 'Webull', 'OrderProcessor')
            include_console: Whether to include console output
        
        Returns:
            Configured logging.Logger instance
        """
        if name in self.loggers:
            return self.loggers[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        
        logger.addHandler(self.main_handler)
        logger.addHandler(self.debug_handler)
        
        if include_console and not getattr(sys, 'frozen', False):
            logger.addHandler(self.console_handler)
        
        logger.propagate = False
        self.loggers[name] = logger
        
        return logger
    
    def get_log_file_path(self) -> str:
        """Get path to the main log file"""
        return str(self.log_dir / 'botifytrades.log')
    
    def get_log_directory_path(self) -> str:
        """Get path to the log directory"""
        return str(self.log_dir)
    
    def open_log_directory(self):
        """Open the log directory in file explorer"""
        import subprocess
        if sys.platform == 'win32':
            os.startfile(str(self.log_dir))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(self.log_dir)])
        else:
            subprocess.run(['xdg-open', str(self.log_dir)])


_logging_service: Optional[LoggingService] = None


def get_logging_service() -> LoggingService:
    """Get the global LoggingService instance"""
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService()
    return _logging_service


def get_logger(name: str, include_console: bool = True) -> logging.Logger:
    """Convenience function to get a logger"""
    return get_logging_service().get_logger(name, include_console)
