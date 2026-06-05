"""
Channel Configuration Page - Step 5
Configure which Discord channels to monitor with per-channel settings
"""

from typing import Dict, Any, Tuple, List, Optional
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QLineEdit, QComboBox,
        QCheckBox, QListWidget, QListWidgetItem,
        QTextEdit, QSpinBox, QGroupBox, QScrollArea
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QLineEdit, QComboBox,
        QCheckBox, QListWidget, QListWidgetItem,
        QTextEdit, QSpinBox, QGroupBox, QScrollArea
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class ChannelConfigCard(QFrame):
    """Configuration card for a single channel - matches web GUI layout"""
    
    removed = Signal(str)
    
    def __init__(self, channel_id: str, channel_name: str, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id
        self.channel_name = channel_name
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(20, 24, 33, 0.95),
                    stop:1 rgba(14, 17, 23, 0.95));
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
                padding: 20px;
            }
            QFrame:hover {
                border-color: rgba(0, 212, 255, 0.3);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        header = QHBoxLayout()
        
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        
        name_label = QLabel(f"#{self.channel_name}")
        name_label.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 600; background: transparent; border: none;")
        info_layout.addWidget(name_label)
        
        id_label = QLabel(self.channel_id)
        id_label.setStyleSheet("""
            color: rgba(255, 255, 255, 0.4);
            font-size: 11px;
            font-family: monospace;
            background: rgba(255, 255, 255, 0.05);
            padding: 4px 10px;
            border-radius: 6px;
            border: none;
        """)
        info_layout.addWidget(id_label)
        header.addWidget(info_widget)
        
        header.addStretch()
        
        remove_btn = QPushButton("✕")
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 8px;
                color: #ef4444;
                font-size: 14px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.1);
                border-color: #ef4444;
            }
        """)
        remove_btn.clicked.connect(lambda: self.removed.emit(self.channel_id))
        header.addWidget(remove_btn)
        
        layout.addLayout(header)
        
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(16)
        
        execute_group = QFrame()
        execute_group.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 12px;
                padding: 14px;
                border: none;
            }
        """)
        execute_layout = QVBoxLayout(execute_group)
        execute_layout.setSpacing(10)
        
        execute_header = QHBoxLayout()
        execute_label = QLabel("Execute Trades")
        execute_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); font-size: 12px; background: transparent; border: none;")
        execute_header.addWidget(execute_label)
        execute_header.addStretch()
        self.execute_check = QCheckBox()
        self.execute_check.setChecked(True)
        self.execute_check.setStyleSheet("""
            QCheckBox::indicator {
                width: 44px;
                height: 24px;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.1);
            }
            QCheckBox::indicator:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #10b981, stop:1 #059669);
            }
        """)
        execute_header.addWidget(self.execute_check)
        execute_layout.addLayout(execute_header)
        
        exec_size_layout = QHBoxLayout()
        exec_size_layout.setSpacing(8)
        self.exec_position_size = QSpinBox()
        self.exec_position_size.setRange(1, 100)
        self.exec_position_size.setValue(5)
        self.exec_position_size.setStyleSheet("""
            QSpinBox {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 8px;
                padding: 8px 12px;
                color: #ffffff;
                font-size: 14px;
                min-width: 60px;
            }
            QSpinBox:focus {
                border-color: #10b981;
            }
        """)
        exec_size_layout.addWidget(self.exec_position_size)
        exec_pct_label = QLabel("%")
        exec_pct_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 14px; background: transparent; border: none;")
        exec_size_layout.addWidget(exec_pct_label)
        exec_size_layout.addStretch()
        execute_layout.addLayout(exec_size_layout)
        
        controls_layout.addWidget(execute_group)
        
        track_group = QFrame()
        track_group.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 12px;
                padding: 14px;
                border: none;
            }
        """)
        track_layout = QVBoxLayout(track_group)
        track_layout.setSpacing(10)
        
        track_header = QHBoxLayout()
        track_label = QLabel("Track Only")
        track_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); font-size: 12px; background: transparent; border: none;")
        track_header.addWidget(track_label)
        track_header.addStretch()
        self.track_check = QCheckBox()
        self.track_check.setStyleSheet("""
            QCheckBox::indicator {
                width: 44px;
                height: 24px;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.1);
            }
            QCheckBox::indicator:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:1 #06b6d4);
            }
        """)
        track_header.addWidget(self.track_check)
        track_layout.addLayout(track_header)
        
        track_size_layout = QHBoxLayout()
        track_size_layout.setSpacing(8)
        self.track_position_size = QSpinBox()
        self.track_position_size.setRange(1, 100)
        self.track_position_size.setValue(5)
        self.track_position_size.setStyleSheet("""
            QSpinBox {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 8px 12px;
                color: #ffffff;
                font-size: 14px;
                min-width: 60px;
            }
            QSpinBox:focus {
                border-color: #00d4ff;
            }
        """)
        track_size_layout.addWidget(self.track_position_size)
        track_pct_label = QLabel("%")
        track_pct_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 14px; background: transparent; border: none;")
        track_size_layout.addWidget(track_pct_label)
        track_size_layout.addStretch()
        track_layout.addLayout(track_size_layout)
        
        controls_layout.addWidget(track_group)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
    
    def get_config(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "execute_enabled": self.execute_check.isChecked(),
            "exec_position_size_pct": self.exec_position_size.value(),
            "track_enabled": self.track_check.isChecked(),
            "track_position_size_pct": self.track_position_size.value()
        }
    
    def set_config(self, config: Dict[str, Any]):
        self.execute_check.setChecked(config.get("execute_enabled", True))
        self.exec_position_size.setValue(config.get("exec_position_size_pct", 5))
        self.track_check.setChecked(config.get("track_enabled", False))
        self.track_position_size.setValue(config.get("track_position_size_pct", 5))


class ChannelConfigPage(BasePage):
    """Channel configuration page"""
    
    def __init__(self, parent=None):
        super().__init__(
            title="Channel Configuration",
            subtitle="Select which Discord channels to monitor and configure their trading rules.",
            parent=parent
        )
        self.channel_cards: Dict[str, ChannelConfigCard] = {}
        self.available_channels: List[Dict] = []
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the channel configuration UI"""
        add_card = QFrame()
        add_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(20, 24, 33, 0.85),
                    stop:1 rgba(14, 17, 23, 0.85));
                border: 2px dashed rgba(15, 240, 179, 0.3);
                border-radius: 20px;
                padding: 24px;
            }
            QFrame:hover {
                border-color: #00d4ff;
            }
        """)
        add_card_layout = QVBoxLayout(add_card)
        add_card_layout.setSpacing(20)
        
        add_title = QLabel("➕ Add New Channel")
        add_title.setStyleSheet("color: #00d4ff; font-size: 16px; font-weight: 600; background: transparent; border: none;")
        add_card_layout.addWidget(add_title)
        
        form_layout = QHBoxLayout()
        form_layout.setSpacing(16)
        
        id_group = QWidget()
        id_layout = QVBoxLayout(id_group)
        id_layout.setContentsMargins(0, 0, 0, 0)
        id_layout.setSpacing(8)
        id_label = QLabel("DISCORD CHANNEL ID")
        id_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); font-size: 11px; font-weight: 500; letter-spacing: 0.5px; background: transparent; border: none;")
        id_layout.addWidget(id_label)
        self.channel_id_input = QLineEdit()
        self.channel_id_input.setPlaceholderText("123456789012345678")
        self.channel_id_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 14px 18px;
                color: #ffffff;
                font-size: 14px;
                min-width: 200px;
            }
            QLineEdit:focus {
                border-color: #00d4ff;
            }
            QLineEdit::placeholder {
                color: rgba(255, 255, 255, 0.3);
            }
        """)
        id_layout.addWidget(self.channel_id_input)
        form_layout.addWidget(id_group)
        
        name_group = QWidget()
        name_layout = QVBoxLayout(name_group)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(8)
        name_label = QLabel("CHANNEL NAME")
        name_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); font-size: 11px; font-weight: 500; letter-spacing: 0.5px; background: transparent; border: none;")
        name_layout.addWidget(name_label)
        self.channel_name_input = QLineEdit()
        self.channel_name_input.setPlaceholderText("my-signals")
        self.channel_name_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 14px 18px;
                color: #ffffff;
                font-size: 14px;
                min-width: 180px;
            }
            QLineEdit:focus {
                border-color: #00d4ff;
            }
            QLineEdit::placeholder {
                color: rgba(255, 255, 255, 0.3);
            }
        """)
        name_layout.addWidget(self.channel_name_input)
        form_layout.addWidget(name_group)
        
        add_btn = QPushButton("➕ Add Channel")
        add_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:1 #7c3aed);
                border: none;
                border-radius: 12px;
                padding: 14px 28px;
                color: #000000;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00b8e0, stop:1 #6d28d9);
            }
        """)
        add_btn.clicked.connect(self._add_channel)
        form_layout.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignBottom)
        
        form_layout.addStretch()
        add_card_layout.addLayout(form_layout)
        
        self.content_layout.addWidget(add_card)
        
        self.content_layout.addSpacing(16)
        
        channels_header = self.create_section_header("Configured Channels")
        self.content_layout.addWidget(channels_header)
        
        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_container)
        self.channels_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.setSpacing(12)
        self.content_layout.addWidget(self.channels_container)
        
        self.no_channels_label = QLabel("No channels configured. Add channels above to start monitoring.")
        self.no_channels_label.setStyleSheet("color: #8b949e; font-size: 14px; padding: 20px;")
        self.no_channels_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.channels_layout.addWidget(self.no_channels_label)
        
        self.content_layout.addSpacing(24)
        self.content_layout.addWidget(self.create_separator())
        self.content_layout.addSpacing(16)
        
        parse_header = self.create_section_header("Signal Parse Test")
        self.content_layout.addWidget(parse_header)
        
        parse_helper = self.create_helper_text(
            "Paste a sample trading alert to test how BotifyTrades will parse it."
        )
        self.content_layout.addWidget(parse_helper)
        
        self.parse_input = QTextEdit()
        self.parse_input.setPlaceholderText("BTO 5 SPY $450 C 12/20 @ 2.50")
        self.parse_input.setMaximumHeight(80)
        self.parse_input.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 10px;
                color: #e6edf3;
                font-size: 14px;
            }
            QTextEdit:focus {
                border-color: #00d4ff;
            }
        """)
        self.content_layout.addWidget(self.parse_input)
        
        parse_btn_layout = QHBoxLayout()
        parse_btn = QPushButton("Test Parse")
        parse_btn.setStyleSheet("""
            QPushButton {
                background-color: #1f6feb;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                color: #ffffff;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #388bfd;
            }
        """)
        parse_btn.clicked.connect(self._test_parse)
        parse_btn_layout.addWidget(parse_btn)
        parse_btn_layout.addStretch()
        self.content_layout.addLayout(parse_btn_layout)
        
        self.parse_result = QLabel("")
        self.parse_result.setStyleSheet("""
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 12px;
            color: #e6edf3;
            font-size: 13px;
        """)
        self.parse_result.setWordWrap(True)
        self.parse_result.hide()
        self.content_layout.addWidget(self.parse_result)
        
        self.validation_label = self.create_validation_label()
        self.content_layout.addWidget(self.validation_label)
        
        self.content_layout.addStretch()
    
    def _add_channel(self):
        """Add a new channel"""
        channel_id = self.channel_id_input.text().strip()
        channel_name = self.channel_name_input.text().strip()
        
        if not channel_id:
            return
        
        if not channel_name:
            channel_name = channel_id
        
        if channel_id in self.channel_cards:
            return
        
        card = ChannelConfigCard(channel_id, channel_name)
        card.removed.connect(self._remove_channel)
        
        self.channel_cards[channel_id] = card
        self.channels_layout.addWidget(card)
        
        self.no_channels_label.hide()
        
        self.channel_id_input.clear()
        self.channel_name_input.clear()
        self.data_changed.emit()
        self.validation_changed.emit(True)
    
    def _remove_channel(self, channel_id: str):
        """Remove a channel"""
        if channel_id in self.channel_cards:
            card = self.channel_cards.pop(channel_id)
            self.channels_layout.removeWidget(card)
            card.deleteLater()
        
        if not self.channel_cards:
            self.no_channels_label.show()
        
        self.data_changed.emit()
        self.validation_changed.emit(len(self.channel_cards) > 0)
    
    def _test_parse(self):
        """Test signal parsing"""
        text = self.parse_input.toPlainText().strip()
        
        if not text:
            self.parse_result.setText("Please enter a signal to parse.")
            self.parse_result.setStyleSheet("""
                background-color: #161b22;
                border: 1px solid #9e6a03;
                border-radius: 6px;
                padding: 12px;
                color: #d29922;
                font-size: 13px;
            """)
            self.parse_result.show()
            return
        
        result = self._mock_parse_signal(text)
        
        if result:
            result_text = (
                f"✓ Signal Parsed Successfully\n\n"
                f"Direction: {result.get('direction', 'N/A')}\n"
                f"Symbol: {result.get('symbol', 'N/A')}\n"
                f"Strike: ${result.get('strike', 'N/A')}\n"
                f"Type: {result.get('option_type', 'N/A')}\n"
                f"Expiry: {result.get('expiry', 'N/A')}\n"
                f"Price: ${result.get('price', 'N/A')}\n"
                f"Quantity: {result.get('quantity', 'N/A')}"
            )
            self.parse_result.setText(result_text)
            self.parse_result.setStyleSheet("""
                background-color: #0f291e;
                border: 1px solid #238636;
                border-radius: 6px;
                padding: 12px;
                color: #00d4ff;
                font-size: 13px;
            """)
        else:
            self.parse_result.setText("✗ Could not parse signal. Check the format.")
            self.parse_result.setStyleSheet("""
                background-color: #2d1b1b;
                border: 1px solid #da3633;
                border-radius: 6px;
                padding: 12px;
                color: #f85149;
                font-size: 13px;
            """)
        
        self.parse_result.show()
    
    def _mock_parse_signal(self, text: str) -> Optional[Dict]:
        """Mock signal parsing for demonstration"""
        import re
        
        pattern = r'(BTO|STC)\s+(\d+)?\s*\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*(\d{1,2}/\d{1,2})\s*@?\s*([\d.]+|[mM])?'
        
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            direction = match.group(1).upper()
            quantity = match.group(2) or "1"
            symbol = match.group(3).upper()
            strike = match.group(4)
            option_type = "CALL" if match.group(5).upper() == "C" else "PUT"
            expiry = match.group(6)
            price = match.group(7) or "MARKET"
            
            return {
                "direction": direction,
                "quantity": quantity,
                "symbol": symbol,
                "strike": strike,
                "option_type": option_type,
                "expiry": expiry,
                "price": price.upper() if price.upper() == "M" else price
            }
        
        return None
    
    def validate(self) -> Tuple[bool, str]:
        """Validate channel configuration"""
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get channel configuration data"""
        channels = []
        for card in self.channel_cards.values():
            channels.append(card.get_config())
        
        return {
            "channels": channels,
            "channel_count": len(channels)
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved channel configuration"""
        for channel_id in list(self.channel_cards.keys()):
            self._remove_channel(channel_id)
        
        for config in data.get("channels", []):
            channel_id = config.get("channel_id")
            channel_name = config.get("channel_name", channel_id)
            
            card = ChannelConfigCard(channel_id, channel_name)
            card.set_config(config)
            card.removed.connect(self._remove_channel)
            
            self.channel_cards[channel_id] = card
            self.channels_layout.addWidget(card)
        
        if self.channel_cards:
            self.no_channels_label.hide()
    
    def can_skip(self) -> bool:
        """Channels can be configured later"""
        return True
