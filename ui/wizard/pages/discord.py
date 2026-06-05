"""
Discord Connection Page - Step 2
Configure Discord bot token and server connection
"""

import asyncio
from typing import Dict, Any, Tuple, Optional
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QLineEdit, QComboBox,
        QRadioButton, QButtonGroup, QListWidget, QListWidgetItem
    )
    from PySide6.QtCore import Qt, Signal, QThread, QObject
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QLineEdit, QComboBox,
        QRadioButton, QButtonGroup, QListWidget, QListWidgetItem
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal, QThread, QObject
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class DiscordTestWorker(QObject):
    """Worker to test Discord connection in background"""
    
    finished = Signal(bool, str, list)
    
    def __init__(self, token: str):
        super().__init__()
        self.token = token
    
    def run(self):
        """Test Discord token and fetch guilds"""
        try:
            import requests
            
            headers = {
                "Authorization": self.token,
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                "https://discord.com/api/v10/users/@me",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 401:
                self.finished.emit(False, "Invalid token", [])
                return
            
            if response.status_code != 200:
                self.finished.emit(False, f"Error: {response.status_code}", [])
                return
            
            user_data = response.json()
            username = user_data.get("username", "Unknown")
            
            guilds_response = requests.get(
                "https://discord.com/api/v10/users/@me/guilds",
                headers=headers,
                timeout=10
            )
            
            guilds = []
            if guilds_response.status_code == 200:
                guilds = guilds_response.json()
            
            self.finished.emit(True, f"Connected as {username}", guilds)
            
        except requests.exceptions.Timeout:
            self.finished.emit(False, "Connection timed out", [])
        except requests.exceptions.ConnectionError:
            self.finished.emit(False, "Could not connect to Discord", [])
        except Exception as e:
            self.finished.emit(False, str(e), [])


class DiscordPage(BasePage):
    """Discord connection configuration page"""
    
    def __init__(self, parent=None):
        super().__init__(
            title="Discord Connection",
            subtitle="Connect your Discord account to monitor trading signal channels.",
            parent=parent
        )
        self.connection_tested = False
        self.guilds = []
        self.test_thread = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the Discord configuration UI"""
        connection_header = self.create_section_header("Connection Method")
        self.content_layout.addWidget(connection_header)
        
        self.bot_token_radio = QRadioButton("Self-Bot Token (Recommended)")
        self.bot_token_radio.setStyleSheet("color: #e6edf3; font-size: 12px;")
        self.bot_token_radio.setChecked(True)
        self.content_layout.addWidget(self.bot_token_radio)
        
        helper = self.create_helper_text(
            "Uses your Discord account token to read messages from channels you have access to."
        )
        self.content_layout.addWidget(helper)
        
        self.content_layout.addSpacing(12)
        
        token_header = self.create_section_header("Discord Token")
        self.content_layout.addWidget(token_header)
        
        token_helper = self.create_helper_text(
            "Your Discord authorization token. Keep this private - never share it with anyone."
        )
        self.content_layout.addWidget(token_helper)
        
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Enter your Discord token...")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setStyleSheet("""
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
        self.token_input.textChanged.connect(self._on_token_changed)
        self.content_layout.addWidget(self.token_input)
        
        show_token_layout = QHBoxLayout()
        self.show_token_btn = QPushButton("👁 Show Token")
        self.show_token_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #8b949e;
                font-size: 11px;
                padding: 2px;
            }
            QPushButton:hover {
                color: #e6edf3;
            }
        """)
        self.show_token_btn.clicked.connect(self._toggle_token_visibility)
        show_token_layout.addWidget(self.show_token_btn)
        show_token_layout.addStretch()
        self.content_layout.addLayout(show_token_layout)
        
        self.content_layout.addSpacing(10)
        
        test_layout = QHBoxLayout()
        
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:1 #0080ff);
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
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
        self.test_btn.clicked.connect(self._test_connection)
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 11px; margin-left: 10px;")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        
        self.content_layout.addLayout(test_layout)
        
        self.content_layout.addSpacing(16)
        self.content_layout.addWidget(self.create_separator())
        self.content_layout.addSpacing(10)
        
        self.server_section = QWidget()
        server_layout = QVBoxLayout(self.server_section)
        server_layout.setContentsMargins(0, 0, 0, 0)
        
        server_header = self.create_section_header("Select Server")
        server_layout.addWidget(server_header)
        
        server_helper = self.create_helper_text(
            "Choose which Discord server to monitor for trading signals."
        )
        server_layout.addWidget(server_helper)
        
        self.server_combo = QComboBox()
        self.server_combo.setStyleSheet("""
            QComboBox {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 8px 10px;
                color: #e6edf3;
                font-size: 12px;
                min-width: 280px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(13, 42, 58, 0.95);
                border: 1px solid rgba(0, 212, 255, 0.2);
                selection-background-color: #00d4ff;
                selection-color: #0d1117;
            }
        """)
        self.server_combo.currentIndexChanged.connect(self._on_server_changed)
        server_layout.addWidget(self.server_combo)
        
        self.server_section.hide()
        self.content_layout.addWidget(self.server_section)
        
        self.validation_label = self.create_validation_label()
        self.content_layout.addWidget(self.validation_label)
        
        self.content_layout.addStretch()
        
        instructions = self.create_card()
        instr_layout = QVBoxLayout(instructions)
        
        instr_title = QLabel("How to get your Discord token:")
        instr_title.setStyleSheet("color: #e6edf3; font-size: 12px; font-weight: 600;")
        instr_layout.addWidget(instr_title)
        
        steps = [
            "1. Open Discord in your web browser",
            "2. Press F12 to open Developer Tools",
            "3. Go to the Network tab",
            "4. Type /api in the filter box",
            "5. Send a message or navigate to a channel",
            "6. Click on any request and find the Authorization header",
            "7. Copy the token value (without quotes)"
        ]
        
        for step in steps:
            step_label = QLabel(step)
            step_label.setStyleSheet("color: #8b949e; font-size: 11px; margin-left: 6px;")
            instr_layout.addWidget(step_label)
        
        self.content_layout.addWidget(instructions)
    
    def _toggle_token_visibility(self):
        """Toggle token visibility"""
        if self.token_input.echoMode() == QLineEdit.EchoMode.Password:
            self.token_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_token_btn.setText("🔒 Hide Token")
        else:
            self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_token_btn.setText("👁 Show Token")
    
    def _on_token_changed(self, text):
        """Handle token input change"""
        self.connection_tested = False
        self.test_status.setText("")
        self.server_section.hide()
        self.server_combo.clear()
        self.guilds = []
        self.validation_changed.emit(False)
        self.data_changed.emit()
    
    def _on_server_changed(self, index):
        """Handle server selection change"""
        self.data_changed.emit()
    
    def _test_connection(self):
        """Test Discord connection"""
        token = self.token_input.text().strip()
        
        if not token:
            self.show_validation_error(self.validation_label, "Please enter a Discord token")
            return
        
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing...")
        self.test_status.setText("")
        self.test_status.setStyleSheet("color: #8b949e; font-size: 14px;")
        
        self.test_thread = QThread()
        self.worker = DiscordTestWorker(token)
        self.worker.moveToThread(self.test_thread)
        
        self.test_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_test_complete)
        self.worker.finished.connect(self.test_thread.quit)
        
        self.test_thread.start()
    
    def _on_test_complete(self, success: bool, message: str, guilds: list):
        """Handle test completion"""
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Connection")
        
        if success:
            self.test_status.setText(f"✓ {message}")
            self.test_status.setStyleSheet("color: #00d4ff; font-size: 11px;")
            self.connection_tested = True
            self.guilds = guilds
            
            self.server_combo.clear()
            for guild in guilds:
                self.server_combo.addItem(guild.get("name", "Unknown"), guild.get("id"))
            
            if guilds:
                self.server_section.show()
            
            self.hide_validation(self.validation_label)
        else:
            self.test_status.setText(f"✗ {message}")
            self.test_status.setStyleSheet("color: #f85149; font-size: 11px;")
            self.connection_tested = False
            self.server_section.hide()
        
        self.validation_changed.emit(self.connection_tested)
        self.data_changed.emit()
    
    def validate(self) -> Tuple[bool, str]:
        """Validate Discord configuration"""
        token = self.token_input.text().strip()
        
        if not token:
            return False, "Discord token is required"
        
        if not self.connection_tested:
            return False, "Please test the Discord connection first"
        
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get Discord configuration data"""
        guild_id = None
        guild_name = None
        
        if self.server_combo.currentIndex() >= 0:
            guild_id = self.server_combo.currentData()
            guild_name = self.server_combo.currentText()
        
        return {
            "discord_token": self.token_input.text().strip(),
            "guild_id": guild_id,
            "guild_name": guild_name,
            "connection_type": "self_bot",
            "guilds": self.guilds
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved Discord configuration"""
        token = data.get("discord_token", "")
        if token:
            self.token_input.setText(token)
        
        guild_id = data.get("guild_id")
        guilds = data.get("guilds", [])
        
        if guilds:
            self.guilds = guilds
            self.server_combo.clear()
            for guild in guilds:
                self.server_combo.addItem(guild.get("name", "Unknown"), guild.get("id"))
            
            if guild_id:
                for i in range(self.server_combo.count()):
                    if self.server_combo.itemData(i) == guild_id:
                        self.server_combo.setCurrentIndex(i)
                        break
            
            self.server_section.show()
            self.connection_tested = True
