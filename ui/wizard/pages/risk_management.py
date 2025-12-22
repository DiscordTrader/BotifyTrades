"""
Risk Management Page - Step 6
Configure global risk settings, stop losses, take profits, and kill switch
"""

from typing import Dict, Any, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QLineEdit, QComboBox,
        QCheckBox, QSpinBox, QDoubleSpinBox, QGroupBox,
        QFormLayout, QSlider
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QLineEdit, QComboBox,
        QCheckBox, QSpinBox, QDoubleSpinBox, QGroupBox,
        QFormLayout, QSlider
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class RiskManagementPage(BasePage):
    """Risk management configuration page"""
    
    def __init__(self, app_mode: str = "paper", parent=None):
        super().__init__(
            title="Risk Management",
            subtitle="Configure your risk parameters to protect your capital.",
            parent=parent
        )
        self.app_mode = app_mode
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the risk management UI"""
        position_group = QGroupBox("Position Sizing")
        position_group.setStyleSheet("""
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
        position_layout = QFormLayout(position_group)
        position_layout.setSpacing(10)
        
        risk_widget = QWidget()
        risk_layout = QHBoxLayout(risk_widget)
        risk_layout.setContentsMargins(0, 0, 0, 0)
        
        self.risk_amount_spin = QDoubleSpinBox()
        self.risk_amount_spin.setRange(0, 100000)
        self.risk_amount_spin.setValue(100)
        self.risk_amount_spin.setPrefix("$")
        self.risk_amount_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                color: #e6edf3;
                min-width: 100px;
            }
        """)
        risk_layout.addWidget(self.risk_amount_spin)
        
        or_label = QLabel("OR")
        or_label.setStyleSheet("color: #8b949e; font-size: 11px; margin: 0 8px;")
        risk_layout.addWidget(or_label)
        
        self.risk_percent_spin = QDoubleSpinBox()
        self.risk_percent_spin.setRange(0, 100)
        self.risk_percent_spin.setValue(2)
        self.risk_percent_spin.setSuffix("%")
        self.risk_percent_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                color: #e6edf3;
                min-width: 80px;
            }
        """)
        risk_layout.addWidget(self.risk_percent_spin)
        risk_layout.addStretch()
        
        position_layout.addRow("Max Risk Per Trade:", risk_widget)
        
        self.max_daily_loss_spin = QDoubleSpinBox()
        self.max_daily_loss_spin.setRange(0, 100000)
        self.max_daily_loss_spin.setValue(500)
        self.max_daily_loss_spin.setPrefix("$")
        self.max_daily_loss_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                color: #e6edf3;
                min-width: 100px;
            }
        """)
        position_layout.addRow("Max Daily Loss:", self.max_daily_loss_spin)
        
        self.max_positions_spin = QSpinBox()
        self.max_positions_spin.setRange(1, 50)
        self.max_positions_spin.setValue(5)
        self.max_positions_spin.setStyleSheet("""
            QSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                color: #e6edf3;
                min-width: 60px;
            }
        """)
        position_layout.addRow("Max Open Positions:", self.max_positions_spin)
        
        self.content_layout.addWidget(position_group)
        
        stop_loss_group = QGroupBox("Stop Loss Settings")
        stop_loss_group.setStyleSheet(position_group.styleSheet())
        stop_loss_layout = QVBoxLayout(stop_loss_group)
        stop_loss_layout.setSpacing(8)
        
        mode_layout = QHBoxLayout()
        mode_label = QLabel("Stop Loss Mode:")
        mode_label.setStyleSheet("color: #e6edf3; font-size: 12px;")
        mode_layout.addWidget(mode_label)
        
        self.stop_mode_combo = QComboBox()
        self.stop_mode_combo.addItems(["Fixed Percentage", "ATR-Based", "None"])
        self.stop_mode_combo.setStyleSheet("""
            QComboBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                color: #e6edf3;
                min-width: 130px;
            }
        """)
        self.stop_mode_combo.currentIndexChanged.connect(self._on_stop_mode_changed)
        mode_layout.addWidget(self.stop_mode_combo)
        mode_layout.addStretch()
        stop_loss_layout.addLayout(mode_layout)
        
        self.stop_percent_widget = QWidget()
        stop_percent_layout = QHBoxLayout(self.stop_percent_widget)
        stop_percent_layout.setContentsMargins(0, 0, 0, 0)
        
        stop_percent_label = QLabel("Stop Loss Percentage:")
        stop_percent_label.setStyleSheet("color: #e6edf3; font-size: 12px;")
        stop_percent_layout.addWidget(stop_percent_label)
        
        self.stop_percent_spin = QDoubleSpinBox()
        self.stop_percent_spin.setRange(0.5, 100)
        self.stop_percent_spin.setValue(10)
        self.stop_percent_spin.setSuffix("%")
        self.stop_percent_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 6px;
                font-size: 12px;
                color: #e6edf3;
            }
        """)
        stop_percent_layout.addWidget(self.stop_percent_spin)
        stop_percent_layout.addStretch()
        stop_loss_layout.addWidget(self.stop_percent_widget)
        
        self.content_layout.addWidget(stop_loss_group)
        
        tp_group = QGroupBox("Take Profit Settings")
        tp_group.setStyleSheet(position_group.styleSheet())
        tp_layout = QVBoxLayout(tp_group)
        tp_layout.setSpacing(8)
        
        tp_header = QLabel("Configure profit targets for partial exits (25% / 50% / Runner)")
        tp_header.setStyleSheet("color: #8b949e; font-size: 11px;")
        tp_layout.addWidget(tp_header)
        
        targets_layout = QHBoxLayout()
        
        tp1_widget = QWidget()
        tp1_layout = QVBoxLayout(tp1_widget)
        tp1_layout.setContentsMargins(0, 0, 0, 0)
        tp1_label = QLabel("Target 1 (25% exit)")
        tp1_label.setStyleSheet("color: #8b949e; font-size: 10px;")
        tp1_layout.addWidget(tp1_label)
        self.tp1_spin = QDoubleSpinBox()
        self.tp1_spin.setRange(1, 500)
        self.tp1_spin.setValue(20)
        self.tp1_spin.setSuffix("% gain")
        self.tp1_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 5px;
                font-size: 11px;
                color: #e6edf3;
            }
        """)
        tp1_layout.addWidget(self.tp1_spin)
        targets_layout.addWidget(tp1_widget)
        
        tp2_widget = QWidget()
        tp2_layout = QVBoxLayout(tp2_widget)
        tp2_layout.setContentsMargins(0, 0, 0, 0)
        tp2_label = QLabel("Target 2 (50% exit)")
        tp2_label.setStyleSheet("color: #8b949e; font-size: 10px;")
        tp2_layout.addWidget(tp2_label)
        self.tp2_spin = QDoubleSpinBox()
        self.tp2_spin.setRange(1, 500)
        self.tp2_spin.setValue(50)
        self.tp2_spin.setSuffix("% gain")
        self.tp2_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 5px;
                font-size: 11px;
                color: #e6edf3;
            }
        """)
        tp2_layout.addWidget(self.tp2_spin)
        targets_layout.addWidget(tp2_widget)
        
        tp3_widget = QWidget()
        tp3_layout = QVBoxLayout(tp3_widget)
        tp3_layout.setContentsMargins(0, 0, 0, 0)
        tp3_label = QLabel("Target 3 (Runner)")
        tp3_label.setStyleSheet("color: #8b949e; font-size: 10px;")
        tp3_layout.addWidget(tp3_label)
        self.tp3_spin = QDoubleSpinBox()
        self.tp3_spin.setRange(1, 1000)
        self.tp3_spin.setValue(100)
        self.tp3_spin.setSuffix("% gain")
        self.tp3_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 5px;
                font-size: 11px;
                color: #e6edf3;
            }
        """)
        tp3_layout.addWidget(self.tp3_spin)
        targets_layout.addWidget(tp3_widget)
        
        targets_layout.addStretch()
        tp_layout.addLayout(targets_layout)
        
        self.trailing_stop_check = QCheckBox("Enable Trailing Stop")
        self.trailing_stop_check.setStyleSheet("color: #e6edf3; font-size: 11px;")
        self.trailing_stop_check.stateChanged.connect(self._on_trailing_changed)
        tp_layout.addWidget(self.trailing_stop_check)
        
        self.trailing_widget = QWidget()
        trailing_layout = QHBoxLayout(self.trailing_widget)
        trailing_layout.setContentsMargins(20, 0, 0, 0)
        trailing_label = QLabel("Trailing Stop Percent:")
        trailing_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        trailing_layout.addWidget(trailing_label)
        self.trailing_percent_spin = QDoubleSpinBox()
        self.trailing_percent_spin.setRange(0.5, 50)
        self.trailing_percent_spin.setValue(5)
        self.trailing_percent_spin.setSuffix("%")
        self.trailing_percent_spin.setStyleSheet("""
            QDoubleSpinBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 5px;
                font-size: 11px;
                color: #e6edf3;
            }
        """)
        trailing_layout.addWidget(self.trailing_percent_spin)
        trailing_layout.addStretch()
        self.trailing_widget.hide()
        tp_layout.addWidget(self.trailing_widget)
        
        self.content_layout.addWidget(tp_group)
        
        killswitch_group = QGroupBox("Emergency Controls")
        killswitch_group.setStyleSheet(position_group.styleSheet())
        killswitch_layout = QVBoxLayout(killswitch_group)
        
        self.killswitch_check = QCheckBox("Enable Kill Switch")
        self.killswitch_check.setStyleSheet("color: #f85149; font-size: 12px; font-weight: 600;")
        killswitch_layout.addWidget(self.killswitch_check)
        
        killswitch_desc = QLabel(
            "When enabled, the kill switch will immediately stop all trading if triggered by "
            "hitting the max daily loss or other critical conditions."
        )
        killswitch_desc.setStyleSheet("color: #8b949e; font-size: 10px; margin-left: 20px;")
        killswitch_desc.setWordWrap(True)
        killswitch_layout.addWidget(killswitch_desc)
        
        self.content_layout.addWidget(killswitch_group)
        
        preview_card = self.create_card()
        preview_layout = QVBoxLayout(preview_card)
        
        preview_title = QLabel("Risk Preview")
        preview_title.setStyleSheet("color: #e6edf3; font-size: 12px; font-weight: 600; border: none;")
        preview_layout.addWidget(preview_title)
        
        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet("color: #00d4ff; font-size: 11px; border: none;")
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        
        self._update_preview()
        
        self.risk_amount_spin.valueChanged.connect(self._update_preview)
        self.risk_percent_spin.valueChanged.connect(self._update_preview)
        self.max_daily_loss_spin.valueChanged.connect(self._update_preview)
        
        self.content_layout.addWidget(preview_card)
        
        self.validation_label = self.create_validation_label()
        self.content_layout.addWidget(self.validation_label)
        
        self.content_layout.addStretch()
    
    def _on_stop_mode_changed(self, index):
        """Handle stop loss mode change"""
        mode = self.stop_mode_combo.currentText()
        self.stop_percent_widget.setVisible(mode != "None")
        self.data_changed.emit()
    
    def _on_trailing_changed(self, state):
        """Handle trailing stop checkbox change"""
        self.trailing_widget.setVisible(state == Qt.CheckState.Checked.value if hasattr(Qt.CheckState, 'Checked') else state == 2)
        self.data_changed.emit()
    
    def _update_preview(self):
        """Update the risk preview text"""
        risk_amount = self.risk_amount_spin.value()
        risk_percent = self.risk_percent_spin.value()
        max_daily = self.max_daily_loss_spin.value()
        
        account_value = risk_amount / (risk_percent / 100) if risk_percent > 0 else 5000
        
        preview_text = (
            f"With a ${account_value:,.0f} account and {risk_percent}% risk per trade, "
            f"you would risk a maximum of ${risk_amount:,.0f} per trade.\n"
            f"Your daily loss limit is set to ${max_daily:,.0f}."
        )
        self.preview_label.setText(preview_text)
    
    def set_app_mode(self, mode: str):
        """Update the app mode"""
        self.app_mode = mode
    
    def validate(self) -> Tuple[bool, str]:
        """Validate risk settings"""
        if self.app_mode in ("paper", "live"):
            if self.risk_amount_spin.value() <= 0 and self.risk_percent_spin.value() <= 0:
                return False, "Please set a maximum risk per trade"
        
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get risk management data"""
        risk_amount = self.risk_amount_spin.value()
        risk_percent = self.risk_percent_spin.value()
        
        if risk_percent > 0:
            position_sizing_mode = 'percent_of_account'
        elif risk_amount > 0:
            position_sizing_mode = 'fixed_amount'
        else:
            position_sizing_mode = 'fixed_amount'
        
        return {
            "position_sizing_mode": position_sizing_mode,
            "risk_per_trade_amount": risk_amount,
            "risk_per_trade_percent": risk_percent,
            "max_position_size": risk_amount * 10 if risk_amount > 0 else 1000,
            "max_daily_loss": self.max_daily_loss_spin.value(),
            "max_open_positions": self.max_positions_spin.value(),
            "stop_loss_mode": self.stop_mode_combo.currentText().lower().replace(" ", "_").replace("-", "_"),
            "stop_loss_percent": self.stop_percent_spin.value(),
            "profit_target_1": self.tp1_spin.value(),
            "profit_target_2": self.tp2_spin.value(),
            "profit_target_3": self.tp3_spin.value(),
            "trailing_stop_enabled": self.trailing_stop_check.isChecked(),
            "trailing_stop_percent": self.trailing_percent_spin.value(),
            "kill_switch_enabled": self.killswitch_check.isChecked(),
            "kill_switch_threshold": self.max_daily_loss_spin.value()
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved risk settings"""
        self.risk_amount_spin.setValue(data.get("risk_per_trade_amount", 100))
        self.risk_percent_spin.setValue(data.get("risk_per_trade_percent", 2))
        self.max_daily_loss_spin.setValue(data.get("max_daily_loss", 500))
        self.max_positions_spin.setValue(data.get("max_open_positions", 5))
        
        mode = data.get("stop_loss_mode", "fixed_percentage")
        mode_map = {"fixed_percentage": 0, "atr_based": 1, "none": 2}
        self.stop_mode_combo.setCurrentIndex(mode_map.get(mode, 0))
        
        self.stop_percent_spin.setValue(data.get("stop_loss_percent", 10))
        self.tp1_spin.setValue(data.get("profit_target_1", 20))
        self.tp2_spin.setValue(data.get("profit_target_2", 50))
        self.tp3_spin.setValue(data.get("profit_target_3", 100))
        self.trailing_stop_check.setChecked(data.get("trailing_stop_enabled", False))
        self.trailing_percent_spin.setValue(data.get("trailing_stop_percent", 5))
        self.killswitch_check.setChecked(data.get("kill_switch_enabled", False))
    
    def can_skip(self) -> bool:
        """Cannot skip risk management for trading modes"""
        return self.app_mode == "alerts"
