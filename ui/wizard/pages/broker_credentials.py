"""
Broker Credentials Page - Step 4
Dynamic credential entry pages for each selected broker
"""

from typing import Dict, Any, Tuple, List, Optional
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QLineEdit, QComboBox,
        QCheckBox, QStackedWidget, QTabWidget,
        QFormLayout, QSpinBox, QDoubleSpinBox
    )
    from PySide6.QtCore import Qt, Signal, QThread, QObject
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QLineEdit, QComboBox,
        QCheckBox, QStackedWidget, QTabWidget,
        QFormLayout, QSpinBox, QDoubleSpinBox
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal, QThread, QObject
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class BrokerCredentialForm(QFrame):
    """Base form for broker credentials"""
    
    test_requested = Signal(str)
    credentials_changed = Signal()
    
    def __init__(self, broker_id: str, broker_name: str, parent=None):
        super().__init__(parent)
        self.broker_id = broker_id
        self.broker_name = broker_name
        self.test_passed = False
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(13, 42, 58, 0.9),
                    stop:1 rgba(15, 58, 79, 0.9));
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 8px;
                padding: 12px;
            }
        """)
    
    def create_password_field(self, placeholder: str = "Enter password...") -> QLineEdit:
        """Create a styled password input field"""
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setStyleSheet("""
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
        field.textChanged.connect(self._on_credentials_changed)
        return field
    
    def create_text_field(self, placeholder: str = "") -> QLineEdit:
        """Create a styled text input field"""
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setStyleSheet("""
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
        field.textChanged.connect(self._on_credentials_changed)
        return field
    
    def create_test_button(self) -> QPushButton:
        """Create a test connection button"""
        btn = QPushButton("Test Login")
        btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:1 #0080ff);
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                color: #ffffff;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00e5ff, stop:1 #0090ff);
            }
            QPushButton:disabled {
                background-color: #21262d;
                color: #484f58;
            }
        """)
        btn.clicked.connect(lambda: self.test_requested.emit(self.broker_id))
        return btn
    
    def _on_credentials_changed(self):
        self.test_passed = False
        self.credentials_changed.emit()
    
    def get_credentials(self) -> Dict[str, Any]:
        """Override in subclass"""
        return {}
    
    def set_credentials(self, data: Dict[str, Any]):
        """Override in subclass"""
        pass
    
    def is_valid(self) -> Tuple[bool, str]:
        """Override in subclass"""
        return True, ""


class WebullCredentialForm(BrokerCredentialForm):
    """Webull-specific credential form with token-based authentication"""
    
    def __init__(self, parent=None):
        super().__init__("webull", "Webull", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 212, 255, 0.15),
                    stop:1 transparent);
                border: none;
                border-left: 3px solid #00d4ff;
                border-radius: 0px;
                padding: 10px;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 6, 10, 6)
        
        title = QLabel("📈 Webull Token Authentication")
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 700; border: none; background: transparent;")
        header_layout.addWidget(title)
        
        desc = QLabel("Webull uses token-based authentication for secure API access. You can obtain your tokens from the Webull desktop app or web interface.")
        desc.setStyleSheet("color: #8899a6; font-size: 11px; border: none; background: transparent;")
        desc.setWordWrap(True)
        header_layout.addWidget(desc)
        layout.addWidget(header_frame)
        
        token_section = QLabel("AUTHENTICATION TOKENS")
        token_section.setStyleSheet("""
            color: #00d4ff;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.2px;
            border: none;
            padding-bottom: 6px;
            border-bottom: 1px solid #1e2936;
        """)
        layout.addWidget(token_section)
        
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.device_id_field = self.create_text_field("Your Webull Device ID")
        self.device_id_field.setMinimumHeight(32)
        device_label = QLabel("Device ID:")
        device_label.setStyleSheet("color: #e6edf3; font-weight: 600; font-size: 11px;")
        form.addRow(device_label, self.device_id_field)
        
        self.access_token_field = self.create_password_field("Your Webull Access Token")
        self.access_token_field.setMinimumHeight(32)
        token_label = QLabel("Access Token:")
        token_label.setStyleSheet("color: #e6edf3; font-weight: 600; font-size: 11px;")
        form.addRow(token_label, self.access_token_field)
        
        self.trade_pin_field = self.create_password_field("6-digit Trading PIN")
        self.trade_pin_field.setMaxLength(6)
        self.trade_pin_field.setMinimumHeight(32)
        pin_label = QLabel("Trade PIN:")
        pin_label.setStyleSheet("color: #e6edf3; font-weight: 600; font-size: 11px;")
        form.addRow(pin_label, self.trade_pin_field)
        
        layout.addLayout(form)
        
        self.paper_mode_check = QCheckBox("Use Paper Trading (Recommended for testing)")
        self.paper_mode_check.setChecked(True)
        self.paper_mode_check.setStyleSheet("""
            QCheckBox {
                color: #e6edf3;
                font-size: 11px;
                border: none;
                spacing: 8px;
            }
        """)
        layout.addWidget(self.paper_mode_check)
        
        test_layout = QHBoxLayout()
        self.test_btn = self.create_test_button()
        self.test_btn.setText("Validate Token")
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px; border: none;")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        layout.addLayout(test_layout)
        
        help_frame = QFrame()
        help_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(42, 58, 74, 0.3);
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 6px;
                padding: 10px;
            }
        """)
        help_layout = QVBoxLayout(help_frame)
        help_layout.setSpacing(4)
        
        help_title = QLabel("💡 How to get your Webull tokens:")
        help_title.setStyleSheet("color: #00d4ff; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        help_layout.addWidget(help_title)
        
        steps = [
            "1. Open Webull desktop app or log into web interface",
            "2. In the bot's Settings page, click 'Connect Webull'",
            "3. Complete login - tokens will be saved automatically",
            "4. Copy Device ID and Access Token here"
        ]
        for step in steps:
            step_label = QLabel(step)
            step_label.setStyleSheet("color: #8899a6; font-size: 10px; border: none; background: transparent; padding-left: 6px;")
            help_layout.addWidget(step_label)
        
        layout.addWidget(help_frame)
    
    def get_credentials(self) -> Dict[str, Any]:
        return {
            "broker": "webull",
            "device_id": self.device_id_field.text().strip(),
            "access_token": self.access_token_field.text().strip(),
            "trade_pin": self.trade_pin_field.text(),
            "paper_trade": self.paper_mode_check.isChecked()
        }
    
    def set_credentials(self, data: Dict[str, Any]):
        self.device_id_field.setText(data.get("device_id", ""))
        self.access_token_field.setText(data.get("access_token", ""))
        self.trade_pin_field.setText(data.get("trade_pin", ""))
        self.paper_mode_check.setChecked(data.get("paper_trade", True))
    
    def is_valid(self) -> Tuple[bool, str]:
        if not self.device_id_field.text().strip():
            return False, "Webull Device ID is required"
        if not self.access_token_field.text().strip():
            return False, "Webull Access Token is required"
        if self.trade_pin_field.text() and len(self.trade_pin_field.text()) != 6:
            return False, "Trade PIN must be 6 digits"
        return True, ""


class AlpacaCredentialForm(BrokerCredentialForm):
    """Alpaca-specific credential form"""
    
    def __init__(self, parent=None):
        super().__init__("alpaca", "Alpaca", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        title = QLabel("🦙 Alpaca Credentials")
        title.setStyleSheet("color: #e6edf3; font-size: 18px; font-weight: 600; border: none;")
        layout.addWidget(title)
        
        desc = QLabel("Enter your Alpaca API credentials. You can find these in your Alpaca dashboard.")
        desc.setStyleSheet("color: #8b949e; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        form = QFormLayout()
        form.setSpacing(12)
        
        self.api_key_field = self.create_text_field("APCA-API-KEY-ID")
        form.addRow("API Key:", self.api_key_field)
        
        self.secret_key_field = self.create_password_field("Secret Key")
        form.addRow("Secret Key:", self.secret_key_field)
        
        layout.addLayout(form)
        
        self.paper_mode_check = QCheckBox("Use Paper Trading (Recommended for testing)")
        self.paper_mode_check.setChecked(True)
        self.paper_mode_check.setStyleSheet("color: #e6edf3; font-size: 13px; border: none;")
        layout.addWidget(self.paper_mode_check)
        
        test_layout = QHBoxLayout()
        self.test_btn = self.create_test_button()
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px; border: none;")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        
        layout.addLayout(test_layout)
    
    def get_credentials(self) -> Dict[str, Any]:
        return {
            "broker": "alpaca",
            "api_key": self.api_key_field.text().strip(),
            "secret_key": self.secret_key_field.text(),
            "paper_trade": self.paper_mode_check.isChecked()
        }
    
    def set_credentials(self, data: Dict[str, Any]):
        self.api_key_field.setText(data.get("api_key", ""))
        self.secret_key_field.setText(data.get("secret_key", ""))
        self.paper_mode_check.setChecked(data.get("paper_trade", True))
    
    def is_valid(self) -> Tuple[bool, str]:
        if not self.api_key_field.text().strip():
            return False, "Alpaca API key is required"
        if not self.secret_key_field.text():
            return False, "Alpaca secret key is required"
        return True, ""


class IBKRCredentialForm(BrokerCredentialForm):
    """IBKR-specific credential form"""
    
    def __init__(self, parent=None):
        super().__init__("ibkr", "Interactive Brokers", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        title = QLabel("🏦 Interactive Brokers Credentials")
        title.setStyleSheet("color: #e6edf3; font-size: 18px; font-weight: 600; border: none;")
        layout.addWidget(title)
        
        desc = QLabel("IBKR requires TWS or IB Gateway running. Configure the connection settings below.")
        desc.setStyleSheet("color: #8b949e; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        form = QFormLayout()
        form.setSpacing(12)
        
        self.host_field = self.create_text_field("127.0.0.1")
        self.host_field.setText("127.0.0.1")
        form.addRow("Host:", self.host_field)
        
        self.port_field = QSpinBox()
        self.port_field.setRange(1, 65535)
        self.port_field.setValue(7497)
        self.port_field.setStyleSheet("""
            QSpinBox {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px;
                color: #e6edf3;
            }
        """)
        form.addRow("Port:", self.port_field)
        
        self.client_id_field = QSpinBox()
        self.client_id_field.setRange(1, 999)
        self.client_id_field.setValue(1)
        self.client_id_field.setStyleSheet("""
            QSpinBox {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px;
                color: #e6edf3;
            }
        """)
        form.addRow("Client ID:", self.client_id_field)
        
        layout.addLayout(form)
        
        self.paper_mode_check = QCheckBox("Use Paper Trading (Port 7497)")
        self.paper_mode_check.setChecked(True)
        self.paper_mode_check.stateChanged.connect(self._on_paper_mode_changed)
        self.paper_mode_check.setStyleSheet("color: #e6edf3; font-size: 13px; border: none;")
        layout.addWidget(self.paper_mode_check)
        
        test_layout = QHBoxLayout()
        self.test_btn = self.create_test_button()
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px; border: none;")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        
        layout.addLayout(test_layout)
    
    def _on_paper_mode_changed(self, state):
        if state:
            self.port_field.setValue(7497)
        else:
            self.port_field.setValue(7496)
    
    def get_credentials(self) -> Dict[str, Any]:
        return {
            "broker": "ibkr",
            "host": self.host_field.text().strip(),
            "port": self.port_field.value(),
            "client_id": self.client_id_field.value(),
            "paper_trade": self.paper_mode_check.isChecked()
        }
    
    def set_credentials(self, data: Dict[str, Any]):
        self.host_field.setText(data.get("host", "127.0.0.1"))
        self.port_field.setValue(data.get("port", 7497))
        self.client_id_field.setValue(data.get("client_id", 1))
        self.paper_mode_check.setChecked(data.get("paper_trade", True))
    
    def is_valid(self) -> Tuple[bool, str]:
        if not self.host_field.text().strip():
            return False, "IBKR host is required"
        return True, ""


class TastytradeCredentialForm(BrokerCredentialForm):
    """Tastytrade-specific credential form"""
    
    def __init__(self, parent=None):
        super().__init__("tastytrade", "Tastytrade", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        title = QLabel("🌶️ Tastytrade Credentials")
        title.setStyleSheet("color: #e6edf3; font-size: 18px; font-weight: 600; border: none;")
        layout.addWidget(title)
        
        desc = QLabel("Enter your Tastytrade OAuth2 credentials (preferred) or legacy username/password.")
        desc.setStyleSheet("color: #8b949e; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        form = QFormLayout()
        form.setSpacing(12)
        
        self.client_secret_field = self.create_password_field("Client Secret")
        form.addRow("Client Secret:", self.client_secret_field)
        
        self.refresh_token_field = self.create_password_field("Refresh Token")
        form.addRow("Refresh Token:", self.refresh_token_field)
        
        layout.addLayout(form)
        
        or_label = QLabel("— OR use legacy login —")
        or_label.setStyleSheet("color: #484f58; font-size: 12px; border: none;")
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(or_label)
        
        legacy_form = QFormLayout()
        legacy_form.setSpacing(12)
        
        self.username_field = self.create_text_field("Username")
        legacy_form.addRow("Username:", self.username_field)
        
        self.password_field = self.create_password_field("Password")
        legacy_form.addRow("Password:", self.password_field)
        
        layout.addLayout(legacy_form)
        
        self.paper_mode_check = QCheckBox("Use Sandbox/Paper Trading")
        self.paper_mode_check.setChecked(True)
        self.paper_mode_check.setStyleSheet("color: #e6edf3; font-size: 13px; border: none;")
        layout.addWidget(self.paper_mode_check)
        
        test_layout = QHBoxLayout()
        self.test_btn = self.create_test_button()
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px; border: none;")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        
        layout.addLayout(test_layout)
    
    def get_credentials(self) -> Dict[str, Any]:
        return {
            "broker": "tastytrade",
            "client_secret": self.client_secret_field.text(),
            "refresh_token": self.refresh_token_field.text(),
            "username": self.username_field.text().strip(),
            "password": self.password_field.text(),
            "paper_trade": self.paper_mode_check.isChecked()
        }
    
    def set_credentials(self, data: Dict[str, Any]):
        self.client_secret_field.setText(data.get("client_secret", ""))
        self.refresh_token_field.setText(data.get("refresh_token", ""))
        self.username_field.setText(data.get("username", ""))
        self.password_field.setText(data.get("password", ""))
        self.paper_mode_check.setChecked(data.get("paper_trade", True))
    
    def is_valid(self) -> Tuple[bool, str]:
        has_oauth = self.client_secret_field.text() and self.refresh_token_field.text()
        has_legacy = self.username_field.text().strip() and self.password_field.text()
        
        if not has_oauth and not has_legacy:
            return False, "Either OAuth2 credentials or username/password is required"
        return True, ""


class RobinhoodCredentialForm(BrokerCredentialForm):
    """Robinhood-specific credential form"""
    
    def __init__(self, parent=None):
        super().__init__("robinhood", "Robinhood", parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        title = QLabel("🪶 Robinhood Credentials")
        title.setStyleSheet("color: #e6edf3; font-size: 18px; font-weight: 600; border: none;")
        layout.addWidget(title)
        
        warning = QFrame()
        warning.setStyleSheet("""
            QFrame {
                background-color: #1c1c17;
                border: 1px solid #9e6a03;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        warning_layout = QVBoxLayout(warning)
        warning_title = QLabel("⚠️ WARNING: NO PAPER TRADING")
        warning_title.setStyleSheet("color: #d29922; font-weight: 600; font-size: 14px; border: none;")
        warning_layout.addWidget(warning_title)
        warning_text = QLabel("Robinhood does not support paper trading. All trades executed through this broker will use REAL money.")
        warning_text.setStyleSheet("color: #d29922; font-size: 12px; border: none;")
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        layout.addWidget(warning)
        
        form = QFormLayout()
        form.setSpacing(12)
        
        self.email_field = self.create_text_field("email@example.com")
        form.addRow("Email:", self.email_field)
        
        self.password_field = self.create_password_field("Password")
        form.addRow("Password:", self.password_field)
        
        self.totp_secret_field = self.create_password_field("TOTP Secret (from 2FA setup)")
        form.addRow("2FA Secret:", self.totp_secret_field)
        
        layout.addLayout(form)
        
        totp_help = QLabel("The TOTP secret is the key shown when setting up 2FA in the Robinhood app.")
        totp_help.setStyleSheet("color: #8b949e; font-size: 11px; border: none;")
        totp_help.setWordWrap(True)
        layout.addWidget(totp_help)
        
        test_layout = QHBoxLayout()
        self.test_btn = self.create_test_button()
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px; border: none;")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        
        layout.addLayout(test_layout)
    
    def get_credentials(self) -> Dict[str, Any]:
        return {
            "broker": "robinhood",
            "email": self.email_field.text().strip(),
            "password": self.password_field.text(),
            "totp_secret": self.totp_secret_field.text().strip(),
            "paper_trade": False
        }
    
    def set_credentials(self, data: Dict[str, Any]):
        self.email_field.setText(data.get("email", ""))
        self.password_field.setText(data.get("password", ""))
        self.totp_secret_field.setText(data.get("totp_secret", ""))
    
    def is_valid(self) -> Tuple[bool, str]:
        if not self.email_field.text().strip():
            return False, "Robinhood email is required"
        if not self.password_field.text():
            return False, "Robinhood password is required"
        return True, ""


class BrokerCredentialsPage(BasePage):
    """Broker credentials configuration page"""
    
    def __init__(self, parent=None):
        super().__init__(
            title="Broker Credentials",
            subtitle="Enter your login credentials for each selected broker.",
            parent=parent
        )
        self.selected_brokers: List[str] = []
        self.credential_forms: Dict[str, BrokerCredentialForm] = {}
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the credentials UI with tabs for each broker"""
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #30363d;
                border-radius: 6px;
                background-color: #0d1117;
            }
            QTabBar::tab {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 10px 20px;
                margin-right: 2px;
                color: #8b949e;
            }
            QTabBar::tab:hover {
                background-color: #21262d;
                color: #e6edf3;
            }
            QTabBar::tab:selected {
                background-color: #0d1117;
                color: #e6edf3;
            }
        """)
        self.content_layout.addWidget(self.tabs)
        
        self.no_brokers_label = QLabel("No brokers selected. Go back to select at least one broker.")
        self.no_brokers_label.setStyleSheet("color: #8b949e; font-size: 14px; padding: 40px;")
        self.no_brokers_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(self.no_brokers_label)
        
        self.validation_label = self.create_validation_label()
        self.content_layout.addWidget(self.validation_label)
        
        self.content_layout.addStretch()
    
    def set_selected_brokers(self, brokers: List[str]):
        """Update the selected brokers and rebuild tabs"""
        self.selected_brokers = brokers
        
        self.tabs.clear()
        self.credential_forms.clear()
        
        if not brokers:
            self.tabs.hide()
            self.no_brokers_label.show()
            return
        
        self.tabs.show()
        self.no_brokers_label.hide()
        
        broker_forms = {
            "webull": ("📈 Webull", WebullCredentialForm),
            "alpaca": ("🦙 Alpaca", AlpacaCredentialForm),
            "ibkr": ("🏦 IBKR", IBKRCredentialForm),
            "tastytrade": ("🌶️ Tastytrade", TastytradeCredentialForm),
            "robinhood": ("🪶 Robinhood", RobinhoodCredentialForm),
        }
        
        for broker_id in brokers:
            if broker_id in broker_forms:
                title, form_class = broker_forms[broker_id]
                form = form_class()
                form.credentials_changed.connect(self._on_credentials_changed)
                form.test_requested.connect(self._on_test_requested)
                self.credential_forms[broker_id] = form
                self.tabs.addTab(form, title)
    
    def _on_credentials_changed(self):
        """Handle credentials change"""
        self.hide_validation(self.validation_label)
        self.data_changed.emit()
    
    def _on_test_requested(self, broker_id: str):
        """Handle test login request"""
        form = self.credential_forms.get(broker_id)
        if not form:
            return
        
        is_valid, error = form.is_valid()
        if not is_valid:
            form.test_status.setText(f"✗ {error}")
            form.test_status.setStyleSheet("color: #f85149; font-size: 13px; border: none;")
            return
        
        form.test_btn.setEnabled(False)
        form.test_btn.setText("Testing...")
        form.test_status.setText("Connecting...")
        form.test_status.setStyleSheet("color: #8b949e; font-size: 13px; border: none;")
        
        form.test_passed = True
        form.test_status.setText("✓ Connection successful (mock)")
        form.test_status.setStyleSheet("color: #00d4ff; font-size: 13px; border: none;")
        form.test_btn.setEnabled(True)
        form.test_btn.setText("Test Login")
        
        self.validation_changed.emit(self._all_valid())
    
    def _all_valid(self) -> bool:
        """Check if all broker forms are valid"""
        for form in self.credential_forms.values():
            is_valid, _ = form.is_valid()
            if not is_valid:
                return False
        return True
    
    def validate(self) -> Tuple[bool, str]:
        """Validate all broker credentials"""
        if not self.selected_brokers:
            return True, ""
        
        for broker_id, form in self.credential_forms.items():
            is_valid, error = form.is_valid()
            if not is_valid:
                return False, f"{form.broker_name}: {error}"
        
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get all broker credentials"""
        credentials = {}
        for broker_id, form in self.credential_forms.items():
            credentials[broker_id] = form.get_credentials()
        return {
            "broker_credentials": credentials
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved broker credentials"""
        credentials = data.get("broker_credentials", {})
        for broker_id, form in self.credential_forms.items():
            if broker_id in credentials:
                form.set_credentials(credentials[broker_id])
    
    def on_enter(self):
        """Called when entering the page"""
        pass
    
    def can_skip(self) -> bool:
        """Can skip if no brokers selected"""
        return len(self.selected_brokers) == 0
