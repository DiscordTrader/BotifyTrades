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
    """Configuration card for a single channel"""
    
    removed = Signal(str)
    
    def __init__(self, channel_id: str, channel_name: str, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id
        self.channel_name = channel_name
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 16px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        header = QHBoxLayout()
        
        name_label = QLabel(f"#{self.channel_name}")
        name_label.setStyleSheet("color: #e6edf3; font-size: 16px; font-weight: 600;")
        header.addWidget(name_label)
        
        header.addStretch()
        
        remove_btn = QPushButton("✕")
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #8b949e;
                font-size: 16px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                color: #f85149;
            }
        """)
        remove_btn.clicked.connect(lambda: self.removed.emit(self.channel_id))
        header.addWidget(remove_btn)
        
        layout.addLayout(header)
        
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(16)
        
        strategy_widget = QWidget()
        strategy_layout = QVBoxLayout(strategy_widget)
        strategy_layout.setContentsMargins(0, 0, 0, 0)
        strategy_layout.setSpacing(4)
        
        strategy_label = QLabel("Strategy Profile")
        strategy_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        strategy_layout.addWidget(strategy_label)
        
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["Scalp", "Day", "Swing"])
        self.strategy_combo.setStyleSheet("""
            QComboBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 6px 10px;
                color: #e6edf3;
                min-width: 100px;
            }
        """)
        strategy_layout.addWidget(self.strategy_combo)
        settings_layout.addWidget(strategy_widget)
        
        max_trades_widget = QWidget()
        max_trades_layout = QVBoxLayout(max_trades_widget)
        max_trades_layout.setContentsMargins(0, 0, 0, 0)
        max_trades_layout.setSpacing(4)
        
        max_trades_label = QLabel("Max Trades/Day")
        max_trades_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        max_trades_layout.addWidget(max_trades_label)
        
        self.max_trades_spin = QSpinBox()
        self.max_trades_spin.setRange(1, 100)
        self.max_trades_spin.setValue(10)
        self.max_trades_spin.setStyleSheet("""
            QSpinBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 6px;
                color: #e6edf3;
            }
        """)
        max_trades_layout.addWidget(self.max_trades_spin)
        settings_layout.addWidget(max_trades_widget)
        
        max_contracts_widget = QWidget()
        max_contracts_layout = QVBoxLayout(max_contracts_widget)
        max_contracts_layout.setContentsMargins(0, 0, 0, 0)
        max_contracts_layout.setSpacing(4)
        
        max_contracts_label = QLabel("Max Contracts")
        max_contracts_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        max_contracts_layout.addWidget(max_contracts_label)
        
        self.max_contracts_spin = QSpinBox()
        self.max_contracts_spin.setRange(1, 100)
        self.max_contracts_spin.setValue(5)
        self.max_contracts_spin.setStyleSheet("""
            QSpinBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 6px;
                color: #e6edf3;
            }
        """)
        max_contracts_layout.addWidget(self.max_contracts_spin)
        settings_layout.addWidget(max_contracts_widget)
        
        settings_layout.addStretch()
        layout.addLayout(settings_layout)
        
        options_layout = QHBoxLayout()
        options_layout.setSpacing(16)
        
        self.execute_check = QCheckBox("Execute Trades")
        self.execute_check.setChecked(True)
        self.execute_check.setStyleSheet("color: #e6edf3; font-size: 12px;")
        options_layout.addWidget(self.execute_check)
        
        self.track_check = QCheckBox("Track Only")
        self.track_check.setStyleSheet("color: #e6edf3; font-size: 12px;")
        options_layout.addWidget(self.track_check)
        
        self.calls_check = QCheckBox("Calls")
        self.calls_check.setChecked(True)
        self.calls_check.setStyleSheet("color: #e6edf3; font-size: 12px;")
        options_layout.addWidget(self.calls_check)
        
        self.puts_check = QCheckBox("Puts")
        self.puts_check.setChecked(True)
        self.puts_check.setStyleSheet("color: #e6edf3; font-size: 12px;")
        options_layout.addWidget(self.puts_check)
        
        self.dte0_check = QCheckBox("0DTE")
        self.dte0_check.setChecked(True)
        self.dte0_check.setStyleSheet("color: #e6edf3; font-size: 12px;")
        options_layout.addWidget(self.dte0_check)
        
        options_layout.addStretch()
        layout.addLayout(options_layout)
    
    def get_config(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "strategy": self.strategy_combo.currentText().lower(),
            "max_trades_per_day": self.max_trades_spin.value(),
            "max_contracts": self.max_contracts_spin.value(),
            "execute_enabled": self.execute_check.isChecked(),
            "track_enabled": self.track_check.isChecked(),
            "allow_calls": self.calls_check.isChecked(),
            "allow_puts": self.puts_check.isChecked(),
            "allow_0dte": self.dte0_check.isChecked()
        }
    
    def set_config(self, config: Dict[str, Any]):
        strategy = config.get("strategy", "scalp")
        idx = self.strategy_combo.findText(strategy.capitalize())
        if idx >= 0:
            self.strategy_combo.setCurrentIndex(idx)
        
        self.max_trades_spin.setValue(config.get("max_trades_per_day", 10))
        self.max_contracts_spin.setValue(config.get("max_contracts", 5))
        self.execute_check.setChecked(config.get("execute_enabled", True))
        self.track_check.setChecked(config.get("track_enabled", False))
        self.calls_check.setChecked(config.get("allow_calls", True))
        self.puts_check.setChecked(config.get("allow_puts", True))
        self.dte0_check.setChecked(config.get("allow_0dte", True))


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
        add_section = QWidget()
        add_layout = QHBoxLayout(add_section)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(12)
        
        add_label = QLabel("Add Channel:")
        add_label.setStyleSheet("color: #8b949e; font-size: 14px;")
        add_layout.addWidget(add_label)
        
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("Enter channel ID or name...")
        self.channel_input.setStyleSheet("""
            QLineEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 10px 12px;
                color: #e6edf3;
                font-size: 14px;
                min-width: 300px;
            }
            QLineEdit:focus {
                border-color: #4ade80;
            }
        """)
        add_layout.addWidget(self.channel_input)
        
        add_btn = QPushButton("Add Channel")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #4ade80;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                color: #0d1117;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #22c55e;
            }
        """)
        add_btn.clicked.connect(self._add_channel)
        add_layout.addWidget(add_btn)
        
        add_layout.addStretch()
        self.content_layout.addWidget(add_section)
        
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
                border-color: #4ade80;
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
        channel_input = self.channel_input.text().strip()
        
        if not channel_input:
            return
        
        channel_id = channel_input.lstrip("#")
        
        if channel_id in self.channel_cards:
            return
        
        card = ChannelConfigCard(channel_id, channel_id)
        card.removed.connect(self._remove_channel)
        
        self.channel_cards[channel_id] = card
        self.channels_layout.addWidget(card)
        
        self.no_channels_label.hide()
        
        self.channel_input.clear()
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
                color: #4ade80;
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
