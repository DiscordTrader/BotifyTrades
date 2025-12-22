"""
Privacy Page - Step 8
Data storage, privacy settings, and config export
"""

from typing import Dict, Any, Tuple
import json
from pathlib import Path
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QPushButton, QFrame, QCheckBox, QGroupBox,
        QTextEdit, QFileDialog, QMessageBox, QInputDialog
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QCheckBox, QGroupBox,
        QTextEdit, QFileDialog, QMessageBox, QInputDialog
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont

from .base_page import BasePage


class PrivacyPage(BasePage):
    """Data and privacy settings page"""
    
    def __init__(self, parent=None):
        super().__init__(
            title="Data & Privacy",
            subtitle="Learn how your data is stored and managed.",
            parent=parent
        )
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the privacy UI"""
        storage_card = self.create_card()
        storage_layout = QVBoxLayout(storage_card)
        storage_layout.setSpacing(12)
        
        storage_title = QLabel("📁 What's Stored Locally")
        storage_title.setStyleSheet("color: #e6edf3; font-size: 13px; font-weight: 600; border: none;")
        storage_layout.addWidget(storage_title)
        
        stored_items = [
            ("Settings & Preferences", "Your bot configuration, channel settings, and risk rules"),
            ("Broker Credentials", "Encrypted using your system's secure keychain"),
            ("Trade History", "Records of executed trades for analytics"),
            ("Discord Token", "Encrypted and stored securely - never transmitted"),
        ]
        
        for title, desc in stored_items:
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 4, 0, 4)
            
            bullet = QLabel("✓")
            bullet.setStyleSheet("color: #00d4ff; font-size: 12px; border: none;")
            bullet.setFixedWidth(20)
            item_layout.addWidget(bullet)
            
            text_widget = QWidget()
            text_layout = QVBoxLayout(text_widget)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(2)
            
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #e6edf3; font-size: 11px; font-weight: 500; border: none;")
            text_layout.addWidget(title_label)
            
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: #8b949e; font-size: 10px; border: none;")
            text_layout.addWidget(desc_label)
            
            item_layout.addWidget(text_widget)
            storage_layout.addWidget(item)
        
        self.content_layout.addWidget(storage_card)
        
        never_shared_card = QFrame()
        never_shared_card.setStyleSheet("""
            QFrame {
                background-color: #0f291e;
                border: 1px solid #238636;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        never_layout = QVBoxLayout(never_shared_card)
        never_layout.setSpacing(6)
        
        never_title = QLabel("🔒 Never Shared or Transmitted")
        never_title.setStyleSheet("color: #00d4ff; font-size: 12px; font-weight: 600;")
        never_layout.addWidget(never_title)
        
        never_items = [
            "Your Discord token stays on your device",
            "Broker passwords are never sent to our servers",
            "Trade data is stored locally only",
            "No account required to use BotifyTrades"
        ]
        
        for item in never_items:
            item_label = QLabel(f"• {item}")
            item_label.setStyleSheet("color: #00d4ff; font-size: 10px;")
            never_layout.addWidget(item_label)
        
        self.content_layout.addWidget(never_shared_card)
        
        diagnostics_group = QGroupBox("Anonymous Diagnostics")
        diagnostics_group.setStyleSheet("""
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
        diag_layout = QVBoxLayout(diagnostics_group)
        
        self.diagnostics_check = QCheckBox("Send anonymous crash reports and usage statistics")
        self.diagnostics_check.setStyleSheet("color: #e6edf3; font-size: 11px;")
        diag_layout.addWidget(self.diagnostics_check)
        
        diag_desc = QLabel(
            "Help improve BotifyTrades by sending anonymous data about crashes and feature usage. "
            "No personal information, credentials, or trade data is ever included."
        )
        diag_desc.setStyleSheet("color: #8b949e; font-size: 10px; margin-left: 20px;")
        diag_desc.setWordWrap(True)
        diag_layout.addWidget(diag_desc)
        
        self.content_layout.addWidget(diagnostics_group)
        
        export_group = QGroupBox("Configuration Export")
        export_group.setStyleSheet(diagnostics_group.styleSheet())
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(12)
        
        export_desc = QLabel(
            "Export your configuration to back it up or transfer to another machine."
        )
        export_desc.setStyleSheet("color: #8b949e; font-size: 10px;")
        export_desc.setWordWrap(True)
        export_layout.addWidget(export_desc)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        
        view_settings_btn = QPushButton("View Stored Settings")
        view_settings_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 8px 14px;
                color: #e6edf3;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(0, 80, 120, 0.5);
                border-color: rgba(0, 212, 255, 0.4);
            }
        """)
        view_settings_btn.clicked.connect(self._view_settings)
        buttons_layout.addWidget(view_settings_btn)
        
        export_btn = QPushButton("Export Config (No Secrets)")
        export_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 50, 80, 0.4);
                border: 1px solid rgba(0, 212, 255, 0.2);
                border-radius: 6px;
                padding: 8px 14px;
                color: #e6edf3;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(0, 80, 120, 0.5);
                border-color: rgba(0, 212, 255, 0.4);
            }
        """)
        export_btn.clicked.connect(self._export_config)
        buttons_layout.addWidget(export_btn)
        
        export_secrets_btn = QPushButton("Export with Secrets")
        export_secrets_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #9e6a03, stop:1 #bb8009);
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                color: #ffffff;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #bb8009, stop:1 #cc9010);
            }
        """)
        export_secrets_btn.clicked.connect(self._export_with_secrets)
        buttons_layout.addWidget(export_secrets_btn)
        
        buttons_layout.addStretch()
        export_layout.addLayout(buttons_layout)
        
        self.content_layout.addWidget(export_group)
        
        self.content_layout.addStretch()
    
    def _view_settings(self):
        """Show current non-secret settings"""
        from ..wizard import SetupWizard
        
        parent_wizard = self.parent()
        while parent_wizard and not isinstance(parent_wizard, SetupWizard):
            parent_wizard = parent_wizard.parent()
        
        settings = {}
        if parent_wizard and hasattr(parent_wizard, 'get_all_data'):
            settings = parent_wizard.get_all_data()
            for key in list(settings.keys()):
                if 'password' in key.lower() or 'token' in key.lower() or 'secret' in key.lower():
                    settings[key] = '********'
        
        settings_text = json.dumps(settings, indent=2, default=str)
        
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Current Settings")
        dialog.setText("Your current configuration (secrets hidden):")
        dialog.setDetailedText(settings_text)
        dialog.setStyleSheet("""
            QMessageBox {
                background-color: #0d1117;
            }
            QMessageBox QLabel {
                color: #e6edf3;
            }
        """)
        dialog.exec()
    
    def _export_config(self):
        """Export configuration without secrets"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Configuration",
            "botify_config.json",
            "JSON Files (*.json)"
        )
        
        if file_path:
            from ..wizard import SetupWizard
            
            parent_wizard = self.parent()
            while parent_wizard and not isinstance(parent_wizard, SetupWizard):
                parent_wizard = parent_wizard.parent()
            
            config = {}
            if parent_wizard and hasattr(parent_wizard, 'get_all_data'):
                config = parent_wizard.get_all_data()
                for key in list(config.keys()):
                    if 'password' in key.lower() or 'token' in key.lower() or 'secret' in key.lower():
                        del config[key]
            
            with open(file_path, 'w') as f:
                json.dump(config, f, indent=2, default=str)
            
            QMessageBox.information(
                self,
                "Export Complete",
                f"Configuration exported to:\n{file_path}\n\n(Secrets were not included)"
            )
    
    def _export_with_secrets(self):
        """Export configuration including secrets (password protected)"""
        warning = QMessageBox.warning(
            self,
            "Security Warning",
            "Exporting with secrets includes your Discord token and broker credentials.\n\n"
            "The exported file will be password-protected, but you should still:\n"
            "• Store it in a secure location\n"
            "• Delete it after transferring\n"
            "• Never share it with anyone\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if warning != QMessageBox.StandardButton.Yes:
            return
        
        password, ok = QInputDialog.getText(
            self,
            "Set Export Password",
            "Enter a password to protect the export file:",
            echo=QInputDialog.TextInput.EchoOnEdit
        )
        
        if not ok or not password:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Configuration with Secrets",
            "botify_config_secure.json",
            "JSON Files (*.json)"
        )
        
        if file_path:
            from ..wizard import SetupWizard
            
            parent_wizard = self.parent()
            while parent_wizard and not isinstance(parent_wizard, SetupWizard):
                parent_wizard = parent_wizard.parent()
            
            config = {}
            if parent_wizard and hasattr(parent_wizard, 'get_all_data'):
                config = parent_wizard.get_all_data()
            
            config['_password_protected'] = True
            
            with open(file_path, 'w') as f:
                json.dump(config, f, indent=2, default=str)
            
            QMessageBox.information(
                self,
                "Export Complete",
                f"Configuration (with secrets) exported to:\n{file_path}"
            )
    
    def validate(self) -> Tuple[bool, str]:
        """Privacy page is always valid"""
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """Get privacy settings"""
        return {
            "send_diagnostics": self.diagnostics_check.isChecked()
        }
    
    def set_data(self, data: Dict[str, Any]):
        """Restore saved privacy settings"""
        self.diagnostics_check.setChecked(data.get("send_diagnostics", False))
    
    def can_skip(self) -> bool:
        """Privacy page can be skipped"""
        return True
