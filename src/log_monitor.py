"""
Log Monitor for AI Chat Assistant
Captures and stores console logs for intelligent analysis
"""

import threading
from collections import deque
from datetime import datetime
from typing import List, Dict, Optional
import re


class LogMonitor:
    """Monitors and captures console logs for AI analysis."""
    
    _instance = None
    _singleton_lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._log_buffer = deque(maxlen=500)
                    instance._trade_logs = deque(maxlen=200)
                    instance._error_logs = deque(maxlen=100)
                    instance._data_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        pass
    
    def capture(self, message: str, level: str = "info"):
        """Capture a log message."""
        with self._data_lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "message": message,
                "level": level,
                "category": self._categorize(message)
            }
            
            self._log_buffer.append(entry)
            
            if entry["category"] in ["trade", "order", "position", "signal"]:
                self._trade_logs.append(entry)
            
            if level in ["error", "critical"] or "[ERROR]" in message or "[CRITICAL]" in message:
                entry["level"] = "error"
                self._error_logs.append(entry)
    
    def _categorize(self, message: str) -> str:
        """Categorize a log message."""
        message_lower = message.lower()
        
        if any(tag in message for tag in ["[BTO]", "[STC]", "[ORDER]", "[FILLED]", "[CANCELLED]"]):
            return "order"
        elif any(tag in message for tag in ["[Signal]", "[SIGNAL PARSED]"]):
            return "signal"
        elif any(tag in message for tag in ["[Position]", "[POSITION SIZE]"]):
            return "position"
        elif any(tag in message for tag in ["[P&L]", "[PNL]"]):
            return "pnl"
        elif any(tag in message for tag in ["[ERROR]", "[CRITICAL]"]):
            return "error"
        elif any(tag in message for tag in ["[WARNING]", "⚠️"]):
            return "warning"
        elif any(tag in message for tag in ["[Webull]", "[ALPACA]", "[IBKR]"]):
            return "broker"
        elif any(tag in message for tag in ["[Discord]", "[Channel]"]):
            return "discord"
        elif any(tag in message for tag in ["[LICENSE]"]):
            return "license"
        elif any(tag in message for tag in ["[STARTUP]", "[Init]", "[GUI]", "[MAIN]"]):
            return "startup"
        else:
            return "general"
    
    def get_recent_logs(self, count: int = 50, category: Optional[str] = None) -> List[Dict]:
        """Get recent logs, optionally filtered by category."""
        with self._data_lock:
            logs = list(self._log_buffer)
            
            if category:
                logs = [l for l in logs if l["category"] == category]
            
            return logs[-count:]
    
    def get_trade_logs(self, count: int = 50) -> List[Dict]:
        """Get recent trade-related logs."""
        with self._data_lock:
            return list(self._trade_logs)[-count:]
    
    def get_error_logs(self, count: int = 20) -> List[Dict]:
        """Get recent error logs."""
        with self._data_lock:
            return list(self._error_logs)[-count:]
    
    def search_logs(self, query: str, count: int = 50) -> List[Dict]:
        """Search logs by keyword."""
        with self._data_lock:
            query_lower = query.lower()
            matches = [
                log for log in self._log_buffer 
                if query_lower in log["message"].lower()
            ]
            return matches[-count:]
    
    def get_summary(self) -> Dict:
        """Get a summary of recent log activity."""
        with self._data_lock:
            total = len(self._log_buffer)
            errors = len([l for l in self._log_buffer if l["level"] == "error"])
            warnings = len([l for l in self._log_buffer if l["category"] == "warning"])
            trades = len(self._trade_logs)
            
            categories = {}
            for log in self._log_buffer:
                cat = log["category"]
                categories[cat] = categories.get(cat, 0) + 1
            
            return {
                "total_logs": total,
                "error_count": errors,
                "warning_count": warnings,
                "trade_count": trades,
                "categories": categories,
                "oldest_log": self._log_buffer[0]["timestamp"] if self._log_buffer else None,
                "newest_log": self._log_buffer[-1]["timestamp"] if self._log_buffer else None
            }
    
    def format_for_ai(self, logs: List[Dict], max_chars: int = 4000) -> str:
        """Format logs for AI analysis."""
        lines = []
        total_chars = 0
        
        for log in reversed(logs):
            line = f"[{log['timestamp'][-8:]}] [{log['category'].upper()}] {log['message']}"
            if total_chars + len(line) > max_chars:
                break
            lines.insert(0, line)
            total_chars += len(line) + 1
        
        return "\n".join(lines)


_monitor = None

def get_log_monitor() -> LogMonitor:
    """Get the global log monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = LogMonitor()
    return _monitor


def capture_log(message: str, level: str = "info"):
    """Capture a log message to the monitor."""
    get_log_monitor().capture(message, level)
