"""
Network Connectivity Monitor - Triggers license validation when internet returns
Detects network state changes and validates license immediately when connectivity is restored.
"""

import socket
import threading
import time
import sys
import os
from datetime import datetime
from typing import Callable, Optional

from .client import LicenseClient


class NetworkMonitor:
    """
    Monitors network connectivity and triggers license validation when internet returns.
    If license is expired/revoked, shuts down the bot with an error message.
    """
    
    def __init__(
        self, 
        license_key: str, 
        check_interval: int = 10,
        shutdown_callback: Optional[Callable] = None,
        show_message_callback: Optional[Callable[[str, str], None]] = None
    ):
        """
        Initialize network monitor.
        
        Args:
            license_key: The license key to validate
            check_interval: Seconds between network checks (default 10)
            shutdown_callback: Function to call when shutting down bot
            show_message_callback: Function to show popup message (title, message)
        """
        self.license_key = license_key
        self.check_interval = check_interval
        self.shutdown_callback = shutdown_callback
        self.show_message_callback = show_message_callback
        
        self.client = LicenseClient()
        self._stop_event = threading.Event()
        self._thread = None
        self._was_offline = False
        self._last_online_check = None
        self._validated_since_online = False
        self._initial_check_done = False
    
    def start(self):
        """Start the network monitoring thread."""
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="NetworkMonitor")
        self._thread.start()
        print("[LICENSE] Network monitor started - will validate on connectivity restore")
    
    def stop(self):
        """Stop the network monitor thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        print("[LICENSE] Network monitor stopped")
    
    def _check_internet(self) -> bool:
        """Check if internet is available by testing DNS resolution."""
        test_hosts = [
            ("8.8.8.8", 53),
            ("1.1.1.1", 53),
            ("api.botifytrades.com", 443),
        ]
        
        for host, port in test_hosts:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.close()
                return True
            except (socket.error, socket.timeout, OSError):
                continue
        
        return False
    
    def _monitor_loop(self):
        """Main monitoring loop - detects connectivity changes."""
        print("[LICENSE] Network monitor loop started")
        
        while not self._stop_event.is_set():
            try:
                is_online = self._check_internet()
                
                if is_online:
                    if self._was_offline or not self._initial_check_done:
                        if self._was_offline:
                            print("[LICENSE] Internet connectivity RESTORED - validating license...")
                        elif not self._validated_since_online:
                            print("[LICENSE] Initial online check - validating license...")
                        self._on_connectivity_restored()
                    self._was_offline = False
                    self._last_online_check = datetime.now()
                    self._initial_check_done = True
                else:
                    if not self._was_offline:
                        print("[LICENSE] Internet connectivity LOST - monitoring for restore...")
                    self._was_offline = True
                    self._validated_since_online = False
                    self._initial_check_done = True
                
            except Exception as e:
                print(f"[LICENSE] Network monitor error: {e}")
            
            self._stop_event.wait(self.check_interval)
        
        print("[LICENSE] Network monitor loop ended")
    
    def _on_connectivity_restored(self):
        """Called when internet connectivity is restored."""
        if self._validated_since_online:
            return
        
        self._validated_since_online = True
        
        try:
            print("[LICENSE] Performing post-reconnect license validation...")
            is_valid, result = self.client.validate_license(self.license_key)
            
            if is_valid:
                print("[LICENSE] License validation successful after reconnect")
                days_remaining = result.get('days_remaining', 'Unknown')
                print(f"[LICENSE] License valid - {days_remaining} days remaining")
            else:
                error = result.get('error', 'License validation failed')
                print(f"[LICENSE] License validation FAILED: {error}")
                self._handle_license_failure(error)
                
        except Exception as e:
            print(f"[LICENSE] Post-reconnect validation error: {e}")
    
    def _handle_license_failure(self, error_message: str):
        """Handle license validation failure - show message and shutdown."""
        print("[LICENSE] =========================================================")
        print("[LICENSE]              LICENSE EXPIRED OR REVOKED                  ")
        print("[LICENSE] =========================================================")
        print(f"[LICENSE] Error: {error_message}")
        print("[LICENSE] The bot will now shut down.")
        print("[LICENSE] Please obtain a new license key to continue using the bot.")
        print("[LICENSE] =========================================================")
        
        title = "License Expired"
        message = (
            "Your license has expired or been revoked.\n\n"
            f"Reason: {error_message}\n\n"
            "Please obtain a new license key to continue using the bot.\n\n"
            "The application will now close."
        )
        
        if self.show_message_callback:
            try:
                self.show_message_callback(title, message)
            except Exception as e:
                print(f"[LICENSE] Could not show popup: {e}")
        
        try:
            from gui_app import database as db
            db.update_setting('license_revoked', 'true')
            db.update_setting('trading_enabled', 'false')
            db.update_setting('license_error', error_message)
        except Exception as e:
            print(f"[LICENSE] Could not update database: {e}")
        
        if self.shutdown_callback:
            try:
                self.shutdown_callback()
            except Exception as e:
                print(f"[LICENSE] Shutdown callback error: {e}")
        
        print("[LICENSE] Forcing application exit...")
        time.sleep(2)
        os._exit(1)


_network_monitor: Optional[NetworkMonitor] = None


def start_network_monitor(
    license_key: str,
    check_interval: int = 10,
    shutdown_callback: Optional[Callable] = None,
    show_message_callback: Optional[Callable[[str, str], None]] = None
) -> NetworkMonitor:
    """
    Start the global network monitor.
    
    Args:
        license_key: The license key to validate
        check_interval: Seconds between checks (default 10)
        shutdown_callback: Function to call on shutdown
        show_message_callback: Function to show popup (title, message)
    
    Returns:
        NetworkMonitor instance
    """
    global _network_monitor
    
    if _network_monitor:
        _network_monitor.stop()
    
    _network_monitor = NetworkMonitor(
        license_key=license_key,
        check_interval=check_interval,
        shutdown_callback=shutdown_callback,
        show_message_callback=show_message_callback
    )
    _network_monitor.start()
    return _network_monitor


def stop_network_monitor():
    """Stop the global network monitor."""
    global _network_monitor
    
    if _network_monitor:
        _network_monitor.stop()
        _network_monitor = None


def show_license_expired_popup(title: str, message: str):
    """
    Show a popup message for license expiry.
    Tries multiple methods: PySide6/PyQt5, tkinter, or console.
    """
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtCore import Qt
        
        app = QApplication.instance()
        if not app:
            app = QApplication([])
        
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.setWindowFlag(Qt.WindowStaysOnTopHint)
        msg_box.exec()
        return
    except ImportError:
        pass
    
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from PyQt5.QtCore import Qt
        
        app = QApplication.instance()
        if not app:
            app = QApplication([])
        
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.setWindowFlag(Qt.WindowStaysOnTopHint)
        msg_box.exec_()
        return
    except ImportError:
        pass
    
    try:
        import tkinter as tk
        from tkinter import messagebox
        
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showerror(title, message)
        root.destroy()
        return
    except ImportError:
        pass
    
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(message)
    print(f"{'='*60}\n")
