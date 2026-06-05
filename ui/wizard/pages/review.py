"""
Review Page - Step 9
Final summary and completion
"""

from typing import Dict, Any, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QScrollArea
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QScrollArea
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class SummaryCard(QFrame):
    """Summary card for displaying configuration section"""
    
    def __init__(self, title: str, icon: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.icon = icon
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 50, 80, 0.4), stop:1 rgba(0, 30, 50, 0.3));
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(6)
        
        header = QHBoxLayout()
        icon_label = QLabel(self.icon)
        icon_label.setStyleSheet("font-size: 16px; border: none;")
        header.addWidget(icon_label)
        
        title_label = QLabel(self.title)
        title_label.setStyleSheet("color: #e6edf3; font-size: 12px; font-weight: 600; border: none;")
        header.addWidget(title_label)
        header.addStretch()
        
        self.layout.addLayout(header)
        
        self.items_widget = QWidget()
        self.items_layout = QVBoxLayout(self.items_widget)
        self.items_layout.setContentsMargins(24, 0, 0, 0)
        self.items_layout.setSpacing(3)
        self.layout.addWidget(self.items_widget)
    
    def add_item(self, label: str, value: str, highlight: bool = False):
        """Add a summary item"""
        item = QHBoxLayout()
        
        label_widget = QLabel(f"{label}:")
        label_widget.setStyleSheet("color: #8b949e; font-size: 10px;")
        label_widget.setMinimumWidth(100)
        item.addWidget(label_widget)
        
        if highlight:
            value_widget = QLabel(value)
            value_widget.setStyleSheet("color: #00d4ff; font-size: 10px; font-weight: 500;")
        else:
            value_widget = QLabel(value)
            value_widget.setStyleSheet("color: #e6edf3; font-size: 10px;")
        
        item.addWidget(value_widget)
        item.addStretch()
        
        self.items_layout.addLayout(item)
    
    def clear_items(self):
        """Clear all items"""
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()


class ReviewPage(BasePage):
    """Final review and completion page"""
    
    finish_clicked = Signal()
    save_exit_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(
            title="Review & Finish",
            subtitle="Review your configuration and start the bot.",
            parent=parent
        )
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the review UI"""
        success_banner = QFrame()
        success_banner.setStyleSheet("""
            QFrame {
                background-color: #0f291e;
                border: 1px solid #238636;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        banner_layout = QHBoxLayout(success_banner)
        
        check_icon = QLabel("✓")
        check_icon.setStyleSheet("color: #00d4ff; font-size: 18px;")
        banner_layout.addWidget(check_icon)
        
        banner_text = QLabel("Setup Complete! Review your configuration below.")
        banner_text.setStyleSheet("color: #00d4ff; font-size: 13px; font-weight: 500;")
        banner_layout.addWidget(banner_text)
        banner_layout.addStretch()
        
        self.content_layout.addWidget(success_banner)
        
        self.content_layout.addSpacing(12)
        
        self.mode_card = SummaryCard("Trading Mode", "📊")
        self.content_layout.addWidget(self.mode_card)
        
        self.discord_card = SummaryCard("Discord Connection", "💬")
        self.content_layout.addWidget(self.discord_card)
        
        self.brokers_card = SummaryCard("Brokers", "🏦")
        self.content_layout.addWidget(self.brokers_card)
        
        self.channels_card = SummaryCard("Channels", "📡")
        self.content_layout.addWidget(self.channels_card)
        
        self.risk_card = SummaryCard("Risk Management", "⚠️")
        self.content_layout.addWidget(self.risk_card)
        
        self.content_layout.addSpacing(16)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        
        self.save_exit_btn = QPushButton("Save & Exit")
        self.save_exit_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 10px 20px;
                color: #e6edf3;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: rgba(0, 80, 120, 0.5);
                border-color: rgba(0, 212, 255, 0.4);
            }
        """)
        self.save_exit_btn.clicked.connect(self.save_exit_clicked.emit)
        buttons_layout.addWidget(self.save_exit_btn)
        
        buttons_layout.addStretch()
        
        self.finish_btn = QPushButton("Finish & Start Bot")
        self.finish_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:1 #0080ff);
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                color: #0d1117;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00e5ff, stop:1 #0090ff);
            }
        """)
        self.finish_btn.clicked.connect(self.finish_clicked.emit)
        buttons_layout.addWidget(self.finish_btn)
        
        self.content_layout.addLayout(buttons_layout)
        
        self.content_layout.addStretch()
    
    def update_summary(self, data: Dict[str, Any]):
        """Update the summary with all wizard data"""
        self.mode_card.clear_items()
        mode = data.get("app_mode", "unknown")
        mode_display = {"alerts": "Alerts Only", "paper": "Paper Trading", "live": "Live Trading"}.get(mode, mode)
        self.mode_card.add_item("Mode", mode_display, highlight=True)
        if data.get("risk_accepted"):
            self.mode_card.add_item("Risk Disclosure", "Accepted")
        
        self.discord_card.clear_items()
        self.discord_card.add_item("Connection", data.get("connection_type", "Not configured"))
        guild_name = data.get("guild_name", "Not selected")
        self.discord_card.add_item("Server", guild_name)
        token = data.get("discord_token", "")
        if token:
            self.discord_card.add_item("Token", f"***{token[-4:]}" if len(token) > 4 else "Set")
        
        self.brokers_card.clear_items()
        selected_brokers = data.get("selected_brokers", [])
        if selected_brokers:
            broker_names = {
                "webull": "Webull",
                "alpaca": "Alpaca",
                "ibkr": "Interactive Brokers",
                "tastytrade": "Tastytrade",
                "robinhood": "Robinhood"
            }
            for broker_id in selected_brokers:
                name = broker_names.get(broker_id, broker_id)
                creds = data.get("broker_credentials", {}).get(broker_id, {})
                paper = creds.get("paper_trade", True)
                mode_str = "Paper" if paper else "Live"
                self.brokers_card.add_item(name, mode_str, highlight=not paper)
        else:
            self.brokers_card.add_item("Selected", "None")
        
        self.channels_card.clear_items()
        channels = data.get("channels", [])
        self.channels_card.add_item("Channels Configured", str(len(channels)))
        if channels:
            for ch in channels[:3]:
                name = ch.get("channel_name", ch.get("channel_id", "Unknown"))
                strategy = ch.get("strategy", "").capitalize()
                self.channels_card.add_item(f"#{name}", strategy)
            if len(channels) > 3:
                self.channels_card.add_item("", f"...and {len(channels) - 3} more")
        
        self.risk_card.clear_items()
        risk_amount = data.get("risk_per_trade_amount", 0)
        risk_percent = data.get("risk_per_trade_percent", 0)
        if risk_amount > 0:
            self.risk_card.add_item("Max Risk/Trade", f"${risk_amount:,.0f}")
        if risk_percent > 0:
            self.risk_card.add_item("Risk Percentage", f"{risk_percent}%")
        self.risk_card.add_item("Max Daily Loss", f"${data.get('max_daily_loss', 0):,.0f}")
        self.risk_card.add_item("Max Positions", str(data.get("max_open_positions", 0)))
        if data.get("kill_switch_enabled"):
            self.risk_card.add_item("Kill Switch", "Enabled", highlight=True)
    
    def validate(self) -> Tuple[bool, str]:
        """Review page is always valid"""
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """No data to collect from review page"""
        return {"setup_reviewed": True}
    
    def on_enter(self):
        """Called when entering the review page"""
        from ..wizard import SetupWizard
        
        parent_wizard = self.parent()
        while parent_wizard and not isinstance(parent_wizard, SetupWizard):
            parent_wizard = parent_wizard.parent()
        
        if parent_wizard and hasattr(parent_wizard, 'get_all_data'):
            all_data = parent_wizard.get_all_data()
            self.update_summary(all_data)
