"""
BotifyTrades System Tray Icon
Provides background operation with tray-based control
"""
import sys
import os
import webbrowser
import threading
from typing import Optional, Callable
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction


class TrayIconManager(QObject):
    """
    System tray icon manager for BotifyTrades.
    Provides status indication and control menu.
    """
    
    show_logs_requested = Signal()
    show_settings_requested = Signal()
    restart_requested = Signal()
    shutdown_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.menu: Optional[QMenu] = None
        self.web_panel_port = 5000
        self._status = "starting"
        self._setup_tray()
    
    def _create_icon(self, status: str = "running") -> QIcon:
        """Create a dynamic tray icon based on status"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if status == "running":
            color = QColor("#22c55e")
        elif status == "starting":
            color = QColor("#f59e0b")
        elif status == "error":
            color = QColor("#ef4444")
        else:
            color = QColor("#6b7280")
        
        painter.setBrush(QColor("#1a1a2e"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
        
        painter.setBrush(color)
        painter.drawEllipse(22, 22, 20, 20)
        
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "BT")
        
        painter.end()
        
        return QIcon(pixmap)
    
    def _setup_tray(self):
        """Setup the system tray icon and menu"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        self.tray_icon = QSystemTrayIcon(self._create_icon("starting"))
        self.tray_icon.setToolTip("BotifyTrades - Starting...")
        
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a2e;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 8px;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2d3748;
            }
            QMenu::separator {
                height: 1px;
                background: #4a5568;
                margin: 5px 10px;
            }
        """)
        
        self.status_action = QAction("Status: Starting...", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        
        self.menu.addSeparator()
        
        open_panel_action = QAction("Open Control Panel", self.menu)
        open_panel_action.triggered.connect(self._open_web_panel)
        self.menu.addAction(open_panel_action)
        
        open_logs_action = QAction("Open Logs Folder", self.menu)
        open_logs_action.triggered.connect(self._open_logs)
        self.menu.addAction(open_logs_action)
        
        self.menu.addSeparator()
        
        restart_action = QAction("Restart Bot", self.menu)
        restart_action.triggered.connect(self._on_restart)
        self.menu.addAction(restart_action)
        
        self.menu.addSeparator()
        
        exit_action = QAction("Exit", self.menu)
        exit_action.triggered.connect(self._on_exit)
        self.menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_activated)
    
    def show(self):
        """Show the tray icon"""
        if self.tray_icon:
            self.tray_icon.show()
    
    def hide(self):
        """Hide the tray icon"""
        if self.tray_icon:
            self.tray_icon.hide()
    
    def set_status(self, status: str, message: str = ""):
        """
        Update tray icon status.
        
        Args:
            status: One of 'running', 'starting', 'error', 'stopped'
            message: Optional status message
        """
        self._status = status
        
        if self.tray_icon:
            self.tray_icon.setIcon(self._create_icon(status))
            
            status_text = {
                "running": "Running",
                "starting": "Starting...",
                "error": "Error",
                "stopped": "Stopped"
            }.get(status, status.title())
            
            tooltip = f"BotifyTrades - {status_text}"
            if message:
                tooltip += f"\n{message}"
            self.tray_icon.setToolTip(tooltip)
            
            if self.status_action:
                self.status_action.setText(f"Status: {status_text}")
    
    def show_notification(self, title: str, message: str, 
                         icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
                         duration_ms: int = 5000):
        """Show a system notification"""
        if self.tray_icon and self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, icon, duration_ms)
    
    def _open_web_panel(self):
        """Open the web control panel in browser"""
        import subprocess
        port = self.web_panel_port or 5000
        url = f"http://localhost:{port}"
        try:
            if sys.platform == 'win32':
                subprocess.Popen(['cmd', '/c', 'start', '', url],
                               shell=False,
                               creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0x08000000)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', url])
            else:
                subprocess.Popen(['xdg-open', url])
        except Exception:
            webbrowser.open(url)
    
    def _open_logs(self):
        """Open the logs folder"""
        try:
            from src.core.logging_service import get_logging_service
            get_logging_service().open_log_directory()
        except ImportError:
            if sys.platform == 'win32':
                log_dir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'BotifyTrades', 'Logs')
                if os.path.exists(log_dir):
                    os.startfile(log_dir)
    
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Handle tray icon activation (double-click)"""
        if reason == QSystemTrayIcon.DoubleClick:
            self._open_web_panel()
    
    def _on_restart(self):
        """Handle restart request"""
        reply = QMessageBox.question(
            None,
            "Restart BotifyTrades",
            "Are you sure you want to restart the bot?\n\nThis will briefly interrupt trading operations.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.restart_requested.emit()
            self.set_status("starting", "Restarting...")
            try:
                from src.services.lifecycle_manager import get_lifecycle_manager
                lifecycle = get_lifecycle_manager()
                def do_restart():
                    lifecycle.restart()
                restart_thread = threading.Thread(target=do_restart, daemon=True)
                restart_thread.start()
            except ImportError:
                pass
    
    def _on_exit(self):
        """Handle exit request"""
        reply = QMessageBox.question(
            None,
            "Exit BotifyTrades",
            "Are you sure you want to exit?\n\nThis will stop all trading operations.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.shutdown_requested.emit()
            if self.tray_icon:
                self.tray_icon.hide()
            try:
                from src.services.lifecycle_manager import get_lifecycle_manager
                lifecycle = get_lifecycle_manager()
                def do_exit():
                    lifecycle.exit(0)
                exit_thread = threading.Thread(target=do_exit, daemon=True)
                exit_thread.start()
            except ImportError:
                QApplication.quit()


_tray_manager: Optional[TrayIconManager] = None


def get_tray_manager() -> TrayIconManager:
    """Get or create the global tray icon manager"""
    global _tray_manager
    if _tray_manager is None:
        _tray_manager = TrayIconManager()
    return _tray_manager


def setup_system_tray() -> TrayIconManager:
    """Setup and show the system tray icon"""
    tray = get_tray_manager()
    tray.show()
    return tray


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    tray = setup_system_tray()
    tray.set_status("starting", "Initializing...")
    
    def simulate_startup():
        QTimer.singleShot(2000, lambda: tray.set_status("running", "Connected to Discord"))
        QTimer.singleShot(2500, lambda: tray.show_notification(
            "BotifyTrades",
            "Bot is now running and monitoring for signals",
            QSystemTrayIcon.MessageIcon.Information
        ))
    
    QTimer.singleShot(500, simulate_startup)
    
    sys.exit(app.exec())
