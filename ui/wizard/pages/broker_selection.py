"""
Broker Selection Page - Step 3
Multi-select list of supported brokers with capability matrix
"""

from typing import Dict, Any, Tuple, List
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QCheckBox, QTableWidget,
        QTableWidgetItem, QHeaderView
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QCheckBox, QTableWidget,
        QTableWidgetItem, QHeaderView
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class BrokerCard(QFrame):
    """Broker selection card with checkbox"""
    
    toggled = Signal(str, bool)
    
    def __init__(self, broker_id: str, name: str, icon: str, description: str, 
                 supports_paper: bool = True, supports_live: bool = True,
                 supports_options: bool = True, warning: str = "", parent=None):
        super().__init__(parent)
        self.broker_id = broker_id
        self.supports_paper = supports_paper
        self.supports_live = supports_live
        self.supports_options = supports_options
        self._setup_ui(name, icon, description, warning)
        self._update_style()
    
    def _setup_ui(self, name: str, icon: str, description: str, warning: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        self.checkbox = QCheckBox()
        self.checkbox.stateChanged.connect(self._on_state_changed)
        layout.addWidget(self.checkbox)
        
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 22px;")
        icon_label.setFixedWidth(36)
        layout.addWidget(icon_label)
        
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(3)
        
        name_label = QLabel(name)
        name_label.setStyleSheet("color: #e6edf3; font-size: 13px; font-weight: 600;")
        info_layout.addWidget(name_label)
        
        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)
        
        caps_layout = QHBoxLayout()
        caps_layout.setSpacing(6)
        
        if self.supports_paper:
            paper_badge = QLabel("📝 Paper")
            paper_badge.setStyleSheet("""
                background-color: #238636;
                color: white;
                padding: 1px 6px;
                border-radius: 3px;
                font-size: 9px;
            """)
            caps_layout.addWidget(paper_badge)
        
        if self.supports_live:
            live_badge = QLabel("💰 Live")
            live_badge.setStyleSheet("""
                background-color: #1f6feb;
                color: white;
                padding: 1px 6px;
                border-radius: 3px;
                font-size: 9px;
            """)
            caps_layout.addWidget(live_badge)
        
        if self.supports_options:
            options_badge = QLabel("📊 Options")
            options_badge.setStyleSheet("""
                background-color: #9e6a03;
                color: white;
                padding: 1px 6px;
                border-radius: 3px;
                font-size: 9px;
            """)
            caps_layout.addWidget(options_badge)
        
        caps_layout.addStretch()
        info_layout.addLayout(caps_layout)
        
        if warning:
            warn_label = QLabel(f"⚠️ {warning}")
            warn_label.setStyleSheet("color: #d29922; font-size: 10px; margin-top: 2px;")
            info_layout.addWidget(warn_label)
        
        layout.addWidget(info_widget, 1)
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def _update_style(self):
        if self.checkbox.isChecked():
            self.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(0, 60, 80, 0.95),
                        stop:1 rgba(0, 100, 130, 0.95));
                    border: 2px solid #00d4ff;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba(13, 42, 58, 0.9),
                        stop:1 rgba(15, 58, 79, 0.9));
                    border: 1px solid rgba(0, 212, 255, 0.15);
                    border-radius: 8px;
                }
                QFrame:hover {
                    border-color: rgba(0, 212, 255, 0.4);
                }
            """)
    
    def _on_state_changed(self, state):
        self._update_style()
        self.toggled.emit(self.broker_id, self.checkbox.isChecked())
    
    def is_selected(self) -> bool:
        return self.checkbox.isChecked()
    
    def set_selected(self, selected: bool):
        self.checkbox.setChecked(selected)
    
    def mousePressEvent(self, event):
        self.checkbox.setChecked(not self.checkbox.isChecked())
        super().mousePressEvent(event)


class BrokerSelectionPage(BasePage):
    """Broker selection page"""
    
    def __init__(self, app_mode: str = "paper", parent=None):
        super().__init__(
            title="Select Your Brokers",
            subtitle="Choose which broker accounts you want to connect. You can select multiple brokers.",
            parent=parent
        )
        self.app_mode = app_mode
        self.broker_cards: Dict[str, BrokerCard] = {}
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the broker selection UI"""
        self.webull_card = BrokerCard(
            broker_id="webull",
            name="Webull",
            icon="📈",
            description="Commission-free trading platform with extended hours and paper trading.",
            supports_paper=True,
            supports_live=True,
            supports_options=True
        )
        self.webull_card.toggled.connect(self._on_broker_toggled)
        self.broker_cards["webull"] = self.webull_card
        self.content_layout.addWidget(self.webull_card)
        
        self.alpaca_card = BrokerCard(
            broker_id="alpaca",
            name="Alpaca",
            icon="🦙",
            description="API-first trading platform ideal for algorithmic trading. Supports stocks and options.",
            supports_paper=True,
            supports_live=True,
            supports_options=True
        )
        self.alpaca_card.toggled.connect(self._on_broker_toggled)
        self.broker_cards["alpaca"] = self.alpaca_card
        self.content_layout.addWidget(self.alpaca_card)
        
        self.ibkr_card = BrokerCard(
            broker_id="ibkr",
            name="Interactive Brokers (IBKR)",
            icon="🏦",
            description="Professional-grade broker with access to global markets. Requires TWS or IB Gateway.",
            supports_paper=True,
            supports_live=True,
            supports_options=True,
            warning="Requires TWS or IB Gateway running locally"
        )
        self.ibkr_card.toggled.connect(self._on_broker_toggled)
        self.broker_cards["ibkr"] = self.ibkr_card
        self.content_layout.addWidget(self.ibkr_card)
        
        self.tastytrade_card = BrokerCard(
            broker_id="tastytrade",
            name="Tastytrade",
            icon="🌶️",
            description="Options-focused trading platform with competitive pricing. OAuth2 authentication.",
            supports_paper=True,
            supports_live=True,
            supports_options=True
        )
        self.tastytrade_card.toggled.connect(self._on_broker_toggled)
        self.broker_cards["tastytrade"] = self.tastytrade_card
        self.content_layout.addWidget(self.tastytrade_card)
        
        self.robinhood_card = BrokerCard(
            broker_id="robinhood",
            name="Robinhood",
            icon="🪶",
            description="Popular commission-free trading app. Requires 2FA TOTP for automated login.",
            supports_paper=False,
            supports_live=True,
            supports_options=True,
            warning="NO paper trading - all trades are LIVE with real money"
        )
        self.robinhood_card.toggled.connect(self._on_broker_toggled)
        self.broker_cards["robinhood"] = self.robinhood_card
        self.content_layout.addWidget(self.robinhood_card)
        
        self.content_layout.addSpacing(12)
        self.content_layout.addWidget(self.create_separator())
        self.content_layout.addSpacing(10)
        
        matrix_header = self.create_section_header("Broker Capability Matrix")
        self.content_layout.addWidget(matrix_header)
        
        matrix_table = QTableWidget(5, 5)
        matrix_table.setHorizontalHeaderLabels([
            "Broker", "Paper Trading", "Live Trading", "Options Chain", "Limitations"
        ])
        matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        matrix_table.verticalHeader().setVisible(False)
        matrix_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        matrix_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        matrix_table.setMaximumHeight(160)
        
        brokers_data = [
            ("Webull", "✓", "✓", "✓", "Rate limits on API"),
            ("Alpaca", "✓", "✓", "✓", "200 req/min limit"),
            ("IBKR", "✓", "✓", "✓", "Requires TWS/Gateway"),
            ("Tastytrade", "✓", "✓", "✓", "OAuth2 required"),
            ("Robinhood", "✗", "✓", "✓", "No paper trading, 2FA required"),
        ]
        
        for row, (name, paper, live, options, limits) in enumerate(brokers_data):
            matrix_table.setItem(row, 0, QTableWidgetItem(name))
            matrix_table.setItem(row, 1, QTableWidgetItem(paper))
            matrix_table.setItem(row, 2, QTableWidgetItem(live))
            matrix_table.setItem(row, 3, QTableWidgetItem(options))
            matrix_table.setItem(row, 4, QTableWidgetItem(limits))
        
        matrix_table.setStyleSheet("""
            QTableWidget {
                background: rgba(13, 42, 58, 0.7);
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 6px;
                gridline-color: rgba(0, 212, 255, 0.1);
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 6px;
                color: #e6edf3;
            }
            QHeaderView::section {
                background: rgba(15, 58, 79, 0.9);
                color: #8b949e;
                padding: 8px;
                border: none;
                border-bottom: 1px solid rgba(0, 212, 255, 0.15);
                font-weight: 600;
                font-size: 10px;
            }
        """)
        
        self.content_layout.addWidget(matrix_table)
        
        self.validation_label = self.create_validation_label()
        self.content_layout.addWidget(self.validation_label)
        
        self.content_layout.addStretch()
    
    def _on_broker_toggled(self, broker_id: str, selected: bool):
        """Handle broker selection toggle"""
        self.hide_validation(self.validation_label)
        self.validation_changed.emit(self._has_selection())
        self.data_changed.emit()
    
    def _has_selection(self) -> bool:
        """Check if at least one broker is selected"""
        return any(card.is_selected() for card in self.broker_cards.values())
    
    def set_app_mode(self, mode: str):
        """Update the app mode (affects validation for Robinhood)"""
        self.app_mode = mode
    
    def validate(self) -> Tuple[bool, str]:
        """Validate broker selection"""
        selected = self.get_selected_brokers()
        
        if not selected:
            return False, "Please select at least one broker"
        
        if "robinhood" in selected and self.app_mode == "paper":
            return False, "Robinhood does not support paper trading. Please deselect it or switch to live trading mode."
        
        return True, ""
    
    def get_selected_brokers(self) -> List[str]:
        """Get list of selected broker IDs"""
        return [
            broker_id 
            for broker_id, card in self.broker_cards.items() 
            if card.is_selected()
        ]
    
    def get_data(self) -> Dict[str, Any]:
        """Get broker selection data"""
        selected = self.get_selected_brokers()
        return {
            "selected_brokers": selected,
            "broker_count": len(selected),
            "webull_enabled": "webull" in selected,
            "alpaca_enabled": "alpaca" in selected,
            "ibkr_enabled": "ibkr" in selected,
            "tastytrade_enabled": "tastytrade" in selected,
            "robinhood_enabled": "robinhood" in selected,
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved broker selection"""
        selected = data.get("selected_brokers", [])
        for broker_id, card in self.broker_cards.items():
            card.set_selected(broker_id in selected)
    
    def can_skip(self) -> bool:
        """Can skip if in alerts-only mode"""
        return self.app_mode == "alerts"
