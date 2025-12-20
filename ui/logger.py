"""
Wizard Logger Module
Structured logging for setup wizard events
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class WizardLogger:
    """Handles logging for the setup wizard"""
    
    def __init__(self, log_dir: str = "./logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.app_log = self.log_dir / "app.log"
        self.wizard_log = self.log_dir / "wizard.log"
        
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Set up app and wizard loggers"""
        log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"
        
        self.app_logger = logging.getLogger("botify.app")
        self.app_logger.setLevel(logging.DEBUG)
        
        if not self.app_logger.handlers:
            app_handler = logging.FileHandler(self.app_log, encoding="utf-8")
            app_handler.setFormatter(logging.Formatter(log_format, date_format))
            app_handler.setLevel(logging.DEBUG)
            self.app_logger.addHandler(app_handler)
            
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter(log_format, date_format))
            console_handler.setLevel(logging.INFO)
            self.app_logger.addHandler(console_handler)
        
        self.wizard_logger = logging.getLogger("botify.wizard")
        self.wizard_logger.setLevel(logging.DEBUG)
        
        if not self.wizard_logger.handlers:
            wizard_handler = logging.FileHandler(self.wizard_log, encoding="utf-8")
            wizard_handler.setFormatter(logging.Formatter(log_format, date_format))
            wizard_handler.setLevel(logging.DEBUG)
            self.wizard_logger.addHandler(wizard_handler)
    
    def info(self, message: str, wizard: bool = False):
        """Log info message"""
        logger = self.wizard_logger if wizard else self.app_logger
        logger.info(message)
    
    def debug(self, message: str, wizard: bool = False):
        """Log debug message"""
        logger = self.wizard_logger if wizard else self.app_logger
        logger.debug(message)
    
    def warning(self, message: str, wizard: bool = False):
        """Log warning message"""
        logger = self.wizard_logger if wizard else self.app_logger
        logger.warning(message)
    
    def error(self, message: str, wizard: bool = False, exc_info: bool = False):
        """Log error message"""
        logger = self.wizard_logger if wizard else self.app_logger
        logger.error(message, exc_info=exc_info)
    
    def critical(self, message: str, wizard: bool = False, exc_info: bool = False):
        """Log critical message"""
        logger = self.wizard_logger if wizard else self.app_logger
        logger.critical(message, exc_info=exc_info)
    
    def wizard_event(self, event_type: str, details: Optional[dict] = None):
        """Log wizard-specific event"""
        details_str = f" | {details}" if details else ""
        self.wizard_logger.info(f"WIZARD_EVENT | {event_type}{details_str}")
    
    def step_entered(self, step_name: str, step_index: int):
        """Log when user enters a wizard step"""
        self.wizard_event("STEP_ENTERED", {"step": step_name, "index": step_index})
    
    def step_completed(self, step_name: str, step_index: int):
        """Log when user completes a wizard step"""
        self.wizard_event("STEP_COMPLETED", {"step": step_name, "index": step_index})
    
    def validation_failed(self, step_name: str, field: str, reason: str):
        """Log validation failure"""
        self.wizard_event("VALIDATION_FAILED", {
            "step": step_name, 
            "field": field, 
            "reason": reason
        })
    
    def connection_test(self, service: str, success: bool, error: Optional[str] = None):
        """Log connection test result"""
        self.wizard_event("CONNECTION_TEST", {
            "service": service,
            "success": success,
            "error": error
        })
    
    def wizard_completed(self, settings_summary: dict):
        """Log wizard completion"""
        self.wizard_event("WIZARD_COMPLETED", settings_summary)
    
    def wizard_cancelled(self, last_step: str):
        """Log wizard cancellation"""
        self.wizard_event("WIZARD_CANCELLED", {"last_step": last_step})


_logger_instance: Optional[WizardLogger] = None


def get_logger() -> WizardLogger:
    """Get singleton logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = WizardLogger()
    return _logger_instance
