"""
App Mode Page - Step 1
Select between Alerts-only, Paper Trading, or Live Trading
"""

from typing import Dict, Any, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QRadioButton, QCheckBox,
        QButtonGroup
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QRadioButton, QCheckBox,
        QButtonGroup
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class ModeCard(QFrame):
    """Clickable mode selection card"""
    
    clicked = Signal()
    
    def __init__(self, icon: str, title: str, description: str, warning: str = "", parent=None):
        super().__init__(parent)
        self.selected = False
        self._setup_ui(icon, title, description, warning)
        self._update_style()
    
    def _setup_ui(self, icon: str, title: str, description: str, warning: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)
        
        header = QHBoxLayout()
        
        self.radio = QRadioButton()
        self.radio.setStyleSheet("""
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        header.addWidget(self.radio)
        
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 20px;")
        header.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #e6edf3; font-size: 14px; font-weight: 600;")
        header.addWidget(title_label)
        header.addStretch()
        
        layout.addLayout(header)
        
        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #8b949e; font-size: 11px; margin-left: 28px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        if warning:
            warning_label = QLabel(f"⚠️ {warning}")
            warning_label.setStyleSheet("color: #d29922; font-size: 10px; margin-left: 28px; margin-top: 4px;")
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def _update_style(self):
        if self.selected:
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
    
    def set_selected(self, selected: bool):
        self.selected = selected
        self.radio.setChecked(selected)
        self._update_style()
    
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class AppModePage(BasePage):
    """Application mode selection page"""
    
    def __init__(self, parent=None):
        super().__init__(
            title="Choose Your Trading Mode",
            subtitle="Select how you want to use BotifyTrades. You can change this later in Settings.",
            parent=parent
        )
        self.selected_mode = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the mode selection UI"""
        self.alerts_card = ModeCard(
            icon="📊",
            title="Alerts Only",
            description="Monitor Discord channels and receive notifications for trading signals. No actual trades will be executed.",
        )
        self.alerts_card.clicked.connect(lambda: self._select_mode("alerts"))
        self.content_layout.addWidget(self.alerts_card)
        
        self.paper_card = ModeCard(
            icon="📝",
            title="Paper Trading",
            description="Execute simulated trades using paper/demo accounts. Perfect for testing strategies without risking real money.",
        )
        self.paper_card.clicked.connect(lambda: self._select_mode("paper"))
        self.content_layout.addWidget(self.paper_card)
        
        self.live_card = ModeCard(
            icon="💰",
            title="Live Trading",
            description="Execute real trades with your broker accounts. Requires funded accounts and proper risk management.",
            warning="Real money will be used. Ensure you understand the risks."
        )
        self.live_card.clicked.connect(lambda: self._select_mode("live"))
        self.content_layout.addWidget(self.live_card)
        
        self.button_group = QButtonGroup(self)
        self.button_group.addButton(self.alerts_card.radio, 0)
        self.button_group.addButton(self.paper_card.radio, 1)
        self.button_group.addButton(self.live_card.radio, 2)
        
        self.content_layout.addSpacing(12)
        
        self.warning_box = self.create_warning_box(
            "Important Risk Disclosure",
            "Trading stocks and options involves substantial risk of loss and is not suitable for all investors. "
            "Past performance is not indicative of future results. You should only trade with money you can afford to lose. "
            "BotifyTrades is a tool to assist with trading and does not guarantee profits."
        )
        self.warning_box.hide()
        self.content_layout.addWidget(self.warning_box)
        
        self.accept_check = QCheckBox("I understand and accept the risks of automated trading")
        self.accept_check.setStyleSheet("color: #e6edf3; font-size: 12px; padding: 6px;")
        self.accept_check.stateChanged.connect(self._on_accept_changed)
        self.accept_check.hide()
        self.content_layout.addWidget(self.accept_check)
        
        self.validation_label = self.create_validation_label()
        self.content_layout.addWidget(self.validation_label)
        
        self.content_layout.addStretch()
    
    def _select_mode(self, mode: str):
        """Handle mode selection"""
        self.selected_mode = mode
        
        self.alerts_card.set_selected(mode == "alerts")
        self.paper_card.set_selected(mode == "paper")
        self.live_card.set_selected(mode == "live")
        
        if mode in ("paper", "live"):
            self.warning_box.show()
            self.accept_check.show()
        else:
            self.warning_box.hide()
            self.accept_check.hide()
            self.accept_check.setChecked(False)
        
        self.hide_validation(self.validation_label)
        self.validation_changed.emit(self._is_valid())
        self.data_changed.emit()
    
    def _on_accept_changed(self, state):
        """Handle accept checkbox change"""
        self.validation_changed.emit(self._is_valid())
        self.data_changed.emit()
    
    def _is_valid(self) -> bool:
        """Check if current selection is valid"""
        if not self.selected_mode:
            return False
        if self.selected_mode in ("paper", "live") and not self.accept_check.isChecked():
            return False
        return True
    
    def validate(self) -> Tuple[bool, str]:
        """Validate mode selection"""
        if not self.selected_mode:
            return False, "Please select a trading mode"
        
        if self.selected_mode in ("paper", "live") and not self.accept_check.isChecked():
            return False, "You must accept the risk disclosure to continue"
        
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get selected mode data"""
        return {
            "app_mode": self.selected_mode,
            "trading_enabled": self.selected_mode in ("paper", "live"),
            "paper_trade": self.selected_mode == "paper",
            "live_trade": self.selected_mode == "live",
            "risk_accepted": self.accept_check.isChecked() if self.selected_mode in ("paper", "live") else False
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved mode selection"""
        mode = data.get("app_mode")
        if mode:
            self._select_mode(mode)
        if data.get("risk_accepted"):
            self.accept_check.setChecked(True)
