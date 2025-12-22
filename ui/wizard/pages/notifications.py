"""
Notifications Page - Step 7
Configure notification preferences
"""

from typing import Dict, Any, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QLineEdit, QCheckBox,
        QGroupBox, QFormLayout
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QLineEdit, QCheckBox,
        QGroupBox, QFormLayout
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class NotificationsPage(BasePage):
    """Notification preferences page"""
    
    def __init__(self, parent=None):
        super().__init__(
            title="Notifications",
            subtitle="Choose how you want to be notified about trades and important events.",
            parent=parent
        )
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the notifications UI"""
        discord_group = QGroupBox("Discord Notifications")
        discord_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: 600;
                font-size: 12px;
                color: #e6edf3;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                background-color: #0d1117;
            }
        """)
        discord_layout = QVBoxLayout(discord_group)
        discord_layout.setSpacing(8)
        
        self.discord_reply_check = QCheckBox("Reply to signal messages with trade confirmations")
        self.discord_reply_check.setChecked(True)
        self.discord_reply_check.setStyleSheet("color: #e6edf3; font-size: 11px;")
        discord_layout.addWidget(self.discord_reply_check)
        
        webhook_section = QWidget()
        webhook_layout = QVBoxLayout(webhook_section)
        webhook_layout.setContentsMargins(0, 8, 0, 0)
        webhook_layout.setSpacing(8)
        
        self.webhook_check = QCheckBox("Send notifications to Discord webhook")
        self.webhook_check.setStyleSheet("color: #e6edf3; font-size: 11px;")
        self.webhook_check.stateChanged.connect(self._on_webhook_toggled)
        webhook_layout.addWidget(self.webhook_check)
        
        self.webhook_input_widget = QWidget()
        webhook_input_layout = QHBoxLayout(self.webhook_input_widget)
        webhook_input_layout.setContentsMargins(24, 0, 0, 0)
        
        self.webhook_input = QLineEdit()
        self.webhook_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.webhook_input.setStyleSheet("""
            QLineEdit {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 8px 10px;
                color: #e6edf3;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #00d4ff;
            }
        """)
        webhook_input_layout.addWidget(self.webhook_input)
        
        test_webhook_btn = QPushButton("Test")
        test_webhook_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:1 #0080ff);
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                color: #0d1117;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00e5ff, stop:1 #0090ff);
            }
        """)
        test_webhook_btn.clicked.connect(self._test_webhook)
        webhook_input_layout.addWidget(test_webhook_btn)
        
        self.webhook_input_widget.hide()
        webhook_layout.addWidget(self.webhook_input_widget)
        
        discord_layout.addWidget(webhook_section)
        self.content_layout.addWidget(discord_group)
        
        desktop_group = QGroupBox("Desktop Notifications")
        desktop_group.setStyleSheet(discord_group.styleSheet())
        desktop_layout = QVBoxLayout(desktop_group)
        desktop_layout.setSpacing(8)
        
        self.desktop_enabled_check = QCheckBox("Enable desktop notifications")
        self.desktop_enabled_check.setChecked(True)
        self.desktop_enabled_check.setStyleSheet("color: #e6edf3; font-size: 11px;")
        desktop_layout.addWidget(self.desktop_enabled_check)
        
        notify_options = QWidget()
        options_layout = QVBoxLayout(notify_options)
        options_layout.setContentsMargins(24, 0, 0, 0)
        options_layout.setSpacing(8)
        
        self.notify_bto_check = QCheckBox("Notify on BTO (Buy to Open)")
        self.notify_bto_check.setChecked(True)
        self.notify_bto_check.setStyleSheet("color: #8b949e; font-size: 10px;")
        options_layout.addWidget(self.notify_bto_check)
        
        self.notify_stc_check = QCheckBox("Notify on STC (Sell to Close)")
        self.notify_stc_check.setChecked(True)
        self.notify_stc_check.setStyleSheet("color: #8b949e; font-size: 10px;")
        options_layout.addWidget(self.notify_stc_check)
        
        self.notify_errors_check = QCheckBox("Notify on errors")
        self.notify_errors_check.setChecked(True)
        self.notify_errors_check.setStyleSheet("color: #8b949e; font-size: 10px;")
        options_layout.addWidget(self.notify_errors_check)
        
        self.notify_connection_check = QCheckBox("Notify on connection status changes")
        self.notify_connection_check.setStyleSheet("color: #8b949e; font-size: 10px;")
        options_layout.addWidget(self.notify_connection_check)
        
        desktop_layout.addWidget(notify_options)
        
        test_desktop_btn = QPushButton("Test Desktop Notification")
        test_desktop_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 8px 16px;
                color: #e6edf3;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(0, 80, 120, 0.5);
                border-color: rgba(0, 212, 255, 0.4);
            }
        """)
        test_desktop_btn.clicked.connect(self._test_desktop)
        desktop_layout.addWidget(test_desktop_btn)
        
        self.content_layout.addWidget(desktop_group)
        
        email_group = QGroupBox("Email/SMS Notifications (Optional)")
        email_group.setStyleSheet(discord_group.styleSheet())
        email_layout = QVBoxLayout(email_group)
        email_layout.setSpacing(8)
        
        self.email_enabled_check = QCheckBox("Enable email notifications")
        self.email_enabled_check.setStyleSheet("color: #e6edf3; font-size: 11px;")
        self.email_enabled_check.stateChanged.connect(self._on_email_toggled)
        email_layout.addWidget(self.email_enabled_check)
        
        self.email_input_widget = QWidget()
        email_input_layout = QFormLayout(self.email_input_widget)
        email_input_layout.setContentsMargins(24, 8, 0, 0)
        email_input_layout.setSpacing(12)
        
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your@email.com")
        self.email_input.setStyleSheet("""
            QLineEdit {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 8px 10px;
                color: #e6edf3;
                font-size: 12px;
            }
        """)
        email_input_layout.addRow("Email:", self.email_input)
        
        self.email_input_widget.hide()
        email_layout.addWidget(self.email_input_widget)
        
        coming_soon = QLabel("📧 Email and SMS notifications coming soon!")
        coming_soon.setStyleSheet("color: #8b949e; font-size: 10px; font-style: italic;")
        email_layout.addWidget(coming_soon)
        
        self.content_layout.addWidget(email_group)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px;")
        self.content_layout.addWidget(self.test_status)
        
        self.content_layout.addStretch()
    
    def _on_webhook_toggled(self, state):
        """Handle webhook checkbox toggle"""
        enabled = state == Qt.CheckState.Checked.value if hasattr(Qt.CheckState, 'Checked') else state == 2
        self.webhook_input_widget.setVisible(enabled)
        self.data_changed.emit()
    
    def _on_email_toggled(self, state):
        """Handle email checkbox toggle"""
        enabled = state == Qt.CheckState.Checked.value if hasattr(Qt.CheckState, 'Checked') else state == 2
        self.email_input_widget.setVisible(enabled)
        self.data_changed.emit()
    
    def _test_webhook(self):
        """Test Discord webhook"""
        webhook_url = self.webhook_input.text().strip()
        
        if not webhook_url:
            self.test_status.setText("⚠️ Please enter a webhook URL")
            self.test_status.setStyleSheet("color: #d29922; font-size: 13px;")
            return
        
        try:
            import requests
            
            payload = {
                "content": "🤖 **BotifyTrades Test** - Webhook connection successful!",
                "username": "BotifyTrades"
            }
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            
            if response.status_code == 204:
                self.test_status.setText("✓ Webhook test successful!")
                self.test_status.setStyleSheet("color: #00d4ff; font-size: 13px;")
            else:
                self.test_status.setText(f"✗ Webhook failed: {response.status_code}")
                self.test_status.setStyleSheet("color: #f85149; font-size: 13px;")
                
        except Exception as e:
            self.test_status.setText(f"✗ Error: {str(e)}")
            self.test_status.setStyleSheet("color: #f85149; font-size: 13px;")
    
    def _test_desktop(self):
        """Test desktop notification"""
        try:
            from plyer import notification
            
            notification.notify(
                title="BotifyTrades Test",
                message="Desktop notifications are working!",
                app_name="BotifyTrades",
                timeout=5
            )
            self.test_status.setText("✓ Desktop notification sent!")
            self.test_status.setStyleSheet("color: #00d4ff; font-size: 13px;")
        except ImportError:
            self.test_status.setText("ℹ️ Desktop notifications require 'plyer' package (will work in final build)")
            self.test_status.setStyleSheet("color: #8b949e; font-size: 13px;")
        except Exception as e:
            self.test_status.setText(f"✗ Error: {str(e)}")
            self.test_status.setStyleSheet("color: #f85149; font-size: 13px;")
    
    def validate(self) -> Tuple[bool, str]:
        """Validate notification settings"""
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get notification settings"""
        return {
            "discord_reply_enabled": self.discord_reply_check.isChecked(),
            "webhook_enabled": self.webhook_check.isChecked(),
            "webhook_url": self.webhook_input.text().strip() if self.webhook_check.isChecked() else "",
            "desktop_enabled": self.desktop_enabled_check.isChecked(),
            "notify_bto": self.notify_bto_check.isChecked(),
            "notify_stc": self.notify_stc_check.isChecked(),
            "notify_errors": self.notify_errors_check.isChecked(),
            "notify_connection": self.notify_connection_check.isChecked(),
            "email_enabled": self.email_enabled_check.isChecked(),
            "email_address": self.email_input.text().strip() if self.email_enabled_check.isChecked() else ""
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved notification settings"""
        self.discord_reply_check.setChecked(data.get("discord_reply_enabled", True))
        self.webhook_check.setChecked(data.get("webhook_enabled", False))
        self.webhook_input.setText(data.get("webhook_url", ""))
        self.desktop_enabled_check.setChecked(data.get("desktop_enabled", True))
        self.notify_bto_check.setChecked(data.get("notify_bto", True))
        self.notify_stc_check.setChecked(data.get("notify_stc", True))
        self.notify_errors_check.setChecked(data.get("notify_errors", True))
        self.notify_connection_check.setChecked(data.get("notify_connection", False))
        self.email_enabled_check.setChecked(data.get("email_enabled", False))
        self.email_input.setText(data.get("email_address", ""))
    
    def can_skip(self) -> bool:
        """Notifications can be configured later"""
        return True
