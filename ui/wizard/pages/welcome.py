"""
Welcome Page - Step 0
Initial welcome screen with setup overview
"""

from typing import Dict, Any, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QFileDialog, QMessageBox
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont, QPixmap
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QFileDialog, QMessageBox
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont, QPixmap

from .base_page import BasePage


class WelcomePage(BasePage):
    """Welcome and introduction page"""
    
    import_requested = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(
            title="Welcome to BotifyTrades",
            subtitle="Let's set up your automated trading bot in just a few steps.",
            parent=parent
        )
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the welcome page UI"""
        title_section = QWidget()
        title_layout = QVBoxLayout(title_section)
        title_layout.setContentsMargins(0, 20, 0, 30)
        
        logo_label = QLabel("🤖")
        logo_label.setStyleSheet("font-size: 64px;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(logo_label)
        
        tagline = QLabel("Professional Discord Signal Trading Bot")
        tagline.setStyleSheet("color: #4ade80; font-size: 16px; font-weight: 500;")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(tagline)
        
        self.content_layout.addWidget(title_section)
        
        features_card = self.create_card()
        features_layout = QVBoxLayout(features_card)
        features_layout.setSpacing(16)
        
        features_title = QLabel("What you'll configure:")
        features_title.setStyleSheet("color: #e6edf3; font-size: 16px; font-weight: 600;")
        features_layout.addWidget(features_title)
        
        features = [
            ("📡", "Discord Connection", "Connect to Discord servers and channels"),
            ("🏦", "Broker Accounts", "Set up Webull, Alpaca, IBKR, Tastytrade, or Robinhood"),
            ("📊", "Channel Monitoring", "Choose which channels to monitor for signals"),
            ("⚠️", "Risk Management", "Configure stop losses, profit targets, and position sizing"),
            ("🔔", "Notifications", "Set up alerts for trades and important events"),
        ]
        
        for icon, title, desc in features:
            feature_row = QHBoxLayout()
            feature_row.setSpacing(12)
            
            icon_label = QLabel(icon)
            icon_label.setStyleSheet("font-size: 24px;")
            icon_label.setFixedWidth(40)
            feature_row.addWidget(icon_label)
            
            text_widget = QWidget()
            text_layout = QVBoxLayout(text_widget)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(2)
            
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #e6edf3; font-size: 14px; font-weight: 500;")
            text_layout.addWidget(title_label)
            
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: #8b949e; font-size: 12px;")
            text_layout.addWidget(desc_label)
            
            feature_row.addWidget(text_widget, 1)
            features_layout.addLayout(feature_row)
        
        self.content_layout.addWidget(features_card)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        
        self.start_btn = QPushButton("Start Setup")
        self.start_btn.setObjectName("primary")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4ade80;
                border: none;
                border-radius: 6px;
                padding: 14px 32px;
                color: #0d1117;
                font-size: 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #22c55e;
            }
        """)
        self.start_btn.clicked.connect(self._on_start_clicked)
        
        self.import_btn = QPushButton("Import Existing Config")
        self.import_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 14px 24px;
                color: #e6edf3;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        self.import_btn.clicked.connect(self._on_import_clicked)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.import_btn)
        buttons_layout.addWidget(self.start_btn)
        buttons_layout.addStretch()
        
        self.content_layout.addSpacing(20)
        self.content_layout.addLayout(buttons_layout)
        
        self.content_layout.addStretch()
        
        footer = QLabel("Version 3.2.9 • BotifyTrades © 2025")
        footer.setStyleSheet("color: #484f58; font-size: 11px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(footer)
    
    def _on_start_clicked(self):
        """Handle start button click"""
        self.data_changed.emit()
    
    def _on_import_clicked(self):
        """Handle import config button click"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Configuration",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            self.import_requested.emit(file_path)
    
    def validate(self) -> Tuple[bool, str]:
        """Welcome page is always valid"""
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """No data to collect from welcome page"""
        return {"wizard_started": True}
