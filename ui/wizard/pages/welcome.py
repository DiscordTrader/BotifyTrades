"""
Welcome Page - Step 0
Initial welcome screen with setup overview
"""

from typing import Dict, Any, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QFileDialog, QMessageBox,
        QGridLayout, QGraphicsDropShadowEffect
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont, QPixmap, QColor
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QFileDialog, QMessageBox,
        QGridLayout, QGraphicsDropShadowEffect
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont, QPixmap, QColor

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
    
    def _create_feature_card(self, icon: str, title: str, desc: str) -> QFrame:
        """Create a compact, professional feature card"""
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(13, 42, 58, 0.9),
                    stop:1 rgba(15, 58, 79, 0.9));
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 8px;
                padding: 0px;
            }
            QFrame:hover {
                border: 1px solid rgba(0, 212, 255, 0.35);
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(13, 42, 58, 1),
                    stop:1 rgba(15, 58, 79, 1));
            }
        """)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        
        icon_container = QFrame()
        icon_container.setFixedSize(36, 36)
        icon_container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(0, 212, 255, 0.15),
                    stop:1 rgba(0, 128, 255, 0.1));
                border: 1px solid rgba(0, 212, 255, 0.25);
                border-radius: 8px;
                padding: 0px;
            }
        """)
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon_label)
        layout.addWidget(icon_container)
        
        text_widget = QWidget()
        text_widget.setStyleSheet("background: transparent; border: none;")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            color: #ffffff;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
            background: transparent;
            border: none;
        """)
        text_layout.addWidget(title_label)
        
        desc_label = QLabel(desc)
        desc_label.setStyleSheet("""
            color: rgba(255, 255, 255, 0.5);
            font-size: 10px;
            font-weight: 400;
            background: transparent;
            border: none;
        """)
        text_layout.addWidget(desc_label)
        
        layout.addWidget(text_widget, 1)
        
        return card
    
    def _setup_ui(self):
        """Set up the welcome page UI"""
        header_section = QWidget()
        header_layout = QVBoxLayout(header_section)
        header_layout.setContentsMargins(0, 8, 0, 16)
        header_layout.setSpacing(6)
        
        logo_label = QLabel("🤖")
        logo_label.setStyleSheet("font-size: 48px; background: transparent;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(logo_label)
        
        tagline = QLabel("Professional Discord Signal Trading Bot")
        tagline.setStyleSheet("""
            color: #00d4ff;
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 0.5px;
        """)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(tagline)
        
        self.content_layout.addWidget(header_section)
        
        features_container = QWidget()
        features_container.setStyleSheet("background: transparent;")
        features_main_layout = QVBoxLayout(features_container)
        features_main_layout.setContentsMargins(0, 0, 0, 0)
        features_main_layout.setSpacing(8)
        
        features_title = QLabel("What you'll configure")
        features_title.setStyleSheet("""
            color: rgba(255, 255, 255, 0.7);
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        """)
        features_main_layout.addWidget(features_title)
        
        features_grid = QGridLayout()
        features_grid.setSpacing(8)
        features_grid.setContentsMargins(0, 4, 0, 0)
        
        features = [
            ("📡", "Discord", "Connect servers & channels"),
            ("🏦", "Brokers", "Webull, Alpaca, IBKR+"),
            ("📊", "Channels", "Monitor signal sources"),
            ("⚠️", "Risk", "Stop loss & position sizing"),
            ("🔔", "Alerts", "Trade notifications"),
            ("🔒", "Security", "Encrypted credentials"),
        ]
        
        for i, (icon, title, desc) in enumerate(features):
            card = self._create_feature_card(icon, title, desc)
            row = i // 2
            col = i % 2
            features_grid.addWidget(card, row, col)
        
        features_main_layout.addLayout(features_grid)
        self.content_layout.addWidget(features_container)
        
        self.content_layout.addSpacing(16)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        self.import_btn = QPushButton("Import Config")
        self.import_btn.setStyleSheet("""
            QPushButton {
                background: rgba(30, 41, 54, 0.8);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 10px 20px;
                color: rgba(255, 255, 255, 0.8);
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: rgba(30, 41, 54, 1);
                border: 1px solid rgba(0, 212, 255, 0.4);
                color: #ffffff;
            }
        """)
        self.import_btn.clicked.connect(self._on_import_clicked)
        
        self.start_btn = QPushButton("Start Setup →")
        self.start_btn.setObjectName("primary")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff,
                    stop:1 #0080ff);
                border: none;
                border-radius: 6px;
                padding: 10px 28px;
                color: #0a0e14;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00e5ff,
                    stop:1 #0090ff);
            }
        """)
        self.start_btn.clicked.connect(self._on_start_clicked)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.import_btn)
        buttons_layout.addWidget(self.start_btn)
        buttons_layout.addStretch()
        
        self.content_layout.addLayout(buttons_layout)
        
        self.content_layout.addStretch()
        
        footer = QLabel("v3.2.9 • BotifyTrades © 2025")
        footer.setStyleSheet("color: rgba(255, 255, 255, 0.25); font-size: 10px;")
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
