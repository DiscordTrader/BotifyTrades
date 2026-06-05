"""
Main Setup Wizard Window
Orchestrates all wizard pages with sidebar navigation
"""

from typing import Dict, Any, Optional, List
import json
from pathlib import Path

try:
    from PySide6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QStackedWidget, QMessageBox, QSizePolicy
    )
    from PySide6.QtCore import Qt, Signal, QSize
    from PySide6.QtGui import QFont, QIcon
except ImportError:
    from PyQt5.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QFrame, QStackedWidget, QMessageBox, QSizePolicy
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal, QSize
    from PyQt5.QtGui import QFont, QIcon

from .pages import (
    WelcomePage, AppModePage, DiscordPage, BrokerSelectionPage,
    BrokerCredentialsPage, ChannelConfigPage, RiskManagementPage,
    NotificationsPage, PrivacyPage, ReviewPage
)


class StepButton(QPushButton):
    """Step navigation button in sidebar"""
    
    def __init__(self, step_number: int, title: str, icon: str = "", parent=None):
        super().__init__(parent)
        self.step_number = step_number
        self.step_title = title
        self.step_icon = icon
        self._is_active = False
        self._is_completed = False
        self._is_enabled = False
        
        self.setText(f"  {icon}  {title}" if icon else title)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
    
    def set_active(self, active: bool):
        self._is_active = active
        self.setChecked(active)
        self._update_style()
    
    def set_completed(self, completed: bool):
        self._is_completed = completed
        self._update_style()
    
    def set_step_enabled(self, enabled: bool):
        self._is_enabled = enabled
        self.setEnabled(enabled)
        self._update_style()
    
    def _update_style(self):
        if self._is_active:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #21262d;
                    border: none;
                    border-left: 3px solid #4ade80;
                    padding: 14px 16px;
                    text-align: left;
                    color: #e6edf3;
                    font-size: 13px;
                    font-weight: 600;
                }
            """)
        elif self._is_completed:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-left: 3px solid transparent;
                    padding: 14px 16px;
                    text-align: left;
                    color: #4ade80;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #21262d;
                }
            """)
        elif self._is_enabled:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-left: 3px solid transparent;
                    padding: 14px 16px;
                    text-align: left;
                    color: #8b949e;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #21262d;
                    color: #e6edf3;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-left: 3px solid transparent;
                    padding: 14px 16px;
                    text-align: left;
                    color: #484f58;
                    font-size: 13px;
                }
            """)


class SetupWizard(QMainWindow):
    """Main setup wizard window"""
    
    wizard_completed = Signal(dict)
    wizard_cancelled = Signal()
    
    STEPS = [
        {"title": "Welcome", "icon": "👋"},
        {"title": "Mode Selection", "icon": "🎯"},
        {"title": "Discord Connection", "icon": "📡"},
        {"title": "Select Brokers", "icon": "🏦"},
        {"title": "Broker Credentials", "icon": "🔑"},
        {"title": "Channel Config", "icon": "📊"},
        {"title": "Risk Management", "icon": "⚠️"},
        {"title": "Notifications", "icon": "🔔"},
        {"title": "Data & Privacy", "icon": "🔒"},
        {"title": "Review & Finish", "icon": "✅"},
    ]
    
    def __init__(self, parent=None, db_adapter=None):
        super().__init__(parent)
        self.db_adapter = db_adapter
        self.current_step = 0
        self.completed_steps = set()
        self.step_buttons: List[StepButton] = []
        self.pages: List[QWidget] = []
        
        self._setup_window()
        self._setup_ui()
        self._setup_pages()
        self._connect_signals()
        self._update_navigation()
    
    def _setup_window(self):
        """Configure main window properties"""
        self.setWindowTitle("BotifyTrades - Setup Wizard")
        self.setMinimumSize(1100, 750)
        self.resize(1200, 800)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d1117;
            }
        """)
    
    def _setup_ui(self):
        """Set up the main UI layout"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)
        
        content_area = self._create_content_area()
        main_layout.addWidget(content_area, 1)
    
    def _create_sidebar(self) -> QFrame:
        """Create the sidebar with step navigation"""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet("""
            QFrame#sidebar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f1419,
                    stop:0.5 #141b24,
                    stop:1 #0f1419);
                border-right: 1px solid #1e2936;
            }
        """)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 24, 20, 20)
        
        logo_label = QLabel("🤖 BotifyTrades")
        logo_label.setStyleSheet("""
            color: #ffffff;
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.5px;
        """)
        header_layout.addWidget(logo_label)
        
        setup_label = QLabel("Setup Wizard")
        setup_label.setStyleSheet("color: #4ecdc4; font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-top: 6px;")
        header_layout.addWidget(setup_label)
        
        layout.addWidget(header)
        
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #30363d;")
        layout.addWidget(separator)
        
        steps_container = QWidget()
        steps_layout = QVBoxLayout(steps_container)
        steps_layout.setContentsMargins(0, 16, 0, 16)
        steps_layout.setSpacing(0)
        
        for i, step in enumerate(self.STEPS):
            btn = StepButton(i, step["title"], step["icon"])
            btn.clicked.connect(lambda checked, idx=i: self._on_step_clicked(idx))
            self.step_buttons.append(btn)
            steps_layout.addWidget(btn)
        
        steps_layout.addStretch()
        layout.addWidget(steps_container, 1)
        
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 16, 16, 16)
        
        progress_label = QLabel()
        progress_label.setObjectName("progress_label")
        progress_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(progress_label)
        self.progress_label = progress_label
        
        layout.addWidget(footer)
        
        return sidebar
    
    def _create_content_area(self) -> QWidget:
        """Create the main content area with page stack and navigation buttons"""
        content = QWidget()
        content.setObjectName("main-content")
        content.setStyleSheet("""
            QWidget#main-content {
                background-color: #0d1117;
            }
        """)
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(48, 40, 48, 24)
        layout.setSpacing(0)
        
        self.page_stack = QStackedWidget()
        layout.addWidget(self.page_stack, 1)
        
        nav_container = self._create_navigation_buttons()
        layout.addWidget(nav_container)
        
        return content
    
    def _create_navigation_buttons(self) -> QWidget:
        """Create the bottom navigation buttons"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 24, 0, 0)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 10px 20px;
                color: #8b949e;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #21262d;
                color: #e6edf3;
            }
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn)
        
        layout.addStretch()
        
        self.back_btn = QPushButton("Back")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 10px 24px;
                color: #e6edf3;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
            QPushButton:disabled {
                background-color: #161b22;
                color: #484f58;
                border-color: #21262d;
            }
        """)
        self.back_btn.clicked.connect(self._on_back)
        layout.addWidget(self.back_btn)
        
        self.next_btn = QPushButton("Next")
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #4ade80;
                border: none;
                border-radius: 6px;
                padding: 10px 32px;
                color: #0d1117;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #22c55e;
            }
            QPushButton:disabled {
                background-color: #1c4428;
                color: #3d8b5a;
            }
        """)
        self.next_btn.clicked.connect(self._on_next)
        layout.addWidget(self.next_btn)
        
        return container
    
    def _setup_pages(self):
        """Initialize all wizard pages"""
        self.welcome_page = WelcomePage()
        self.app_mode_page = AppModePage()
        self.discord_page = DiscordPage()
        self.broker_selection_page = BrokerSelectionPage()
        self.broker_credentials_page = BrokerCredentialsPage()
        self.channel_config_page = ChannelConfigPage()
        self.risk_management_page = RiskManagementPage()
        self.notifications_page = NotificationsPage()
        self.privacy_page = PrivacyPage()
        self.review_page = ReviewPage()
        
        self.pages = [
            self.welcome_page,
            self.app_mode_page,
            self.discord_page,
            self.broker_selection_page,
            self.broker_credentials_page,
            self.channel_config_page,
            self.risk_management_page,
            self.notifications_page,
            self.privacy_page,
            self.review_page,
        ]
        
        for page in self.pages:
            self.page_stack.addWidget(page)
    
    def _connect_signals(self):
        """Connect page signals"""
        self.welcome_page.data_changed.connect(lambda: self._on_next())
        
        self.welcome_page.import_requested.connect(self._on_import_config)
        
        self.broker_selection_page.data_changed.connect(self._on_broker_selection_changed)
        
        for page in self.pages:
            if hasattr(page, 'validation_changed'):
                page.validation_changed.connect(self._update_next_button)
    
    def _on_broker_selection_changed(self):
        """Handle broker selection changes"""
        broker_data = self.broker_selection_page.get_data()
        selected_brokers = broker_data.get('selected_brokers', [])
        self.broker_credentials_page.set_selected_brokers(selected_brokers)
    
    def _on_step_clicked(self, step_index: int):
        """Handle sidebar step click"""
        if step_index <= max(self.completed_steps, default=0) + 1:
            if step_index < self.current_step or step_index in self.completed_steps:
                self._go_to_step(step_index)
    
    def _go_to_step(self, step_index: int):
        """Navigate to a specific step"""
        if 0 <= step_index < len(self.pages):
            self.current_step = step_index
            self.page_stack.setCurrentIndex(step_index)
            self._update_navigation()
            
            if step_index == len(self.pages) - 1:
                self._update_review_page()
    
    def _update_navigation(self):
        """Update sidebar and button states"""
        for i, btn in enumerate(self.step_buttons):
            btn.set_active(i == self.current_step)
            btn.set_completed(i in self.completed_steps)
            btn.set_step_enabled(i <= max(self.completed_steps, default=0) + 1)
        
        self.back_btn.setEnabled(self.current_step > 0)
        
        if self.current_step == len(self.pages) - 1:
            self.next_btn.setText("Finish Setup")
        else:
            self.next_btn.setText("Next")
        
        self._update_next_button()
        
        progress = int((len(self.completed_steps) / len(self.pages)) * 100)
        self.progress_label.setText(f"Step {self.current_step + 1} of {len(self.pages)} • {progress}% complete")
    
    def _update_next_button(self):
        """Update next button enabled state based on current page validation"""
        current_page = self.pages[self.current_step]
        if hasattr(current_page, 'validate'):
            is_valid, _ = current_page.validate()
            self.next_btn.setEnabled(is_valid)
        else:
            self.next_btn.setEnabled(True)
    
    def _on_back(self):
        """Handle back button click"""
        if self.current_step > 0:
            self._go_to_step(self.current_step - 1)
    
    def _on_next(self):
        """Handle next button click"""
        current_page = self.pages[self.current_step]
        
        if hasattr(current_page, 'validate'):
            is_valid, error_message = current_page.validate()
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "Validation Error",
                    error_message or "Please complete all required fields."
                )
                return
        
        self.completed_steps.add(self.current_step)
        
        if self.current_step < len(self.pages) - 1:
            self._go_to_step(self.current_step + 1)
        else:
            self._finish_wizard()
    
    def _on_cancel(self):
        """Handle cancel button click"""
        reply = QMessageBox.question(
            self,
            "Cancel Setup",
            "Are you sure you want to cancel the setup wizard?\nAny unsaved changes will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.wizard_cancelled.emit()
            self.close()
    
    def _on_import_config(self, file_path: str):
        """Handle config import from file"""
        try:
            with open(file_path, 'r') as f:
                config = json.load(f)
            
            self._apply_imported_config(config)
            
            QMessageBox.information(
                self,
                "Import Successful",
                "Configuration imported successfully. Please review each step."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import configuration:\n{str(e)}"
            )
    
    def _apply_imported_config(self, config: Dict[str, Any]):
        """Apply imported configuration to pages"""
        if 'app_mode' in config:
            self.app_mode_page.set_data(config.get('app_mode', {}))
        
        if 'discord' in config:
            self.discord_page.set_data(config.get('discord', {}))
        
        if 'brokers' in config:
            self.broker_selection_page.set_data(config.get('brokers', {}))
            self.broker_credentials_page.set_data(config.get('broker_credentials', {}))
        
        if 'channels' in config:
            self.channel_config_page.set_data(config.get('channels', {}))
        
        if 'risk_management' in config:
            self.risk_management_page.set_data(config.get('risk_management', {}))
        
        if 'notifications' in config:
            self.notifications_page.set_data(config.get('notifications', {}))
        
        if 'privacy' in config:
            self.privacy_page.set_data(config.get('privacy', {}))
    
    def _update_review_page(self):
        """Update the review page with all collected data"""
        all_data = self.get_all_data()
        flat_data = self._flatten_wizard_data(all_data)
        self.review_page.update_summary(flat_data)
    
    def _flatten_wizard_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested wizard data for review page"""
        flat = {}
        
        if 'app_mode' in data:
            flat['app_mode'] = data['app_mode'].get('mode', 'unknown')
            flat['risk_accepted'] = data['app_mode'].get('risk_accepted', False)
        
        if 'discord' in data:
            flat['discord_token'] = data['discord'].get('token', '')
            flat['guild_name'] = data['discord'].get('guild_name', '')
            flat['connection_type'] = 'Self-Bot' if data['discord'].get('token') else 'Not configured'
        
        if 'brokers' in data:
            flat['selected_brokers'] = data['brokers'].get('selected_brokers', [])
        
        if 'broker_credentials' in data:
            flat['broker_credentials'] = data['broker_credentials']
        
        if 'channels' in data:
            flat['channels'] = data['channels'].get('channels', [])
        
        if 'risk_management' in data:
            rm = data['risk_management']
            flat['risk_per_trade_amount'] = rm.get('risk_per_trade_amount', 0)
            flat['risk_per_trade_percent'] = rm.get('risk_per_trade_percent', 0)
            flat['max_daily_loss'] = rm.get('max_daily_loss', 0)
            flat['max_open_positions'] = rm.get('max_open_positions', 0)
            flat['kill_switch_enabled'] = rm.get('kill_switch_enabled', False)
        
        return flat
    
    def get_all_data(self) -> Dict[str, Any]:
        """Collect all data from all pages"""
        return {
            'welcome': self.welcome_page.get_data(),
            'app_mode': self.app_mode_page.get_data(),
            'discord': self.discord_page.get_data(),
            'brokers': self.broker_selection_page.get_data(),
            'broker_credentials': self.broker_credentials_page.get_data(),
            'channels': self.channel_config_page.get_data(),
            'risk_management': self.risk_management_page.get_data(),
            'notifications': self.notifications_page.get_data(),
            'privacy': self.privacy_page.get_data(),
        }
    
    def _finish_wizard(self):
        """Complete the wizard and save configuration"""
        all_data = self.get_all_data()
        
        if self.db_adapter:
            try:
                self.db_adapter.save_wizard_config(all_data)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Failed to save configuration:\n{str(e)}"
                )
                return
        
        self.wizard_completed.emit(all_data)
        
        QMessageBox.information(
            self,
            "Setup Complete",
            "BotifyTrades has been configured successfully!\n\n"
            "The bot will now start with your settings."
        )
        
        self.close()
    
    def export_config(self, file_path: str):
        """Export current configuration to file"""
        all_data = self.get_all_data()
        
        export_data = {k: v for k, v in all_data.items() if k != 'broker_credentials'}
        
        with open(file_path, 'w') as f:
            json.dump(export_data, f, indent=2)


def launch_wizard(db_adapter=None) -> Optional[Dict[str, Any]]:
    """Launch the setup wizard and return collected data"""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        from PyQt5.QtWidgets import QApplication
    
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    
    wizard = SetupWizard(db_adapter=db_adapter)
    
    result = {'completed': False, 'data': None}
    
    def on_completed(data):
        result['completed'] = True
        result['data'] = data
    
    wizard.wizard_completed.connect(on_completed)
    wizard.show()
    
    app.exec()
    
    return result['data'] if result['completed'] else None
