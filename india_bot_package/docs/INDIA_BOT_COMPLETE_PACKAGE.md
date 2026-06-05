# India Trading Bot - Complete Package Guide

## Complete Build System with Splash Screen, License Validation, and Background Operation

This guide provides everything needed to set up an India trading bot with:
- **No console window** (runs as GUI app)
- **Splash screen** for license key entry or trial activation
- **Background operation** with system tray icon
- **Stop/Restart buttons** via tray menu and web panel
- **Same license server** as BotifyTrades

---

## Replit Agent Prompt

```
Create a complete trading bot application with:

1. **Startup Flow (No Console)**
   - PyInstaller spec with console=False
   - PySide6 splash screen appears first
   - License validation before main app starts
   - Trial activation option

2. **License System**
   - Connect to license-forge--uk15286.replit.app
   - RSA-signed tokens for offline grace period
   - Machine ID binding
   - Store license in database for persistence

3. **Background Operation**
   - System tray icon with status indicator (green=running, yellow=starting, red=error)
   - Tray menu: Open Control Panel, Restart Bot, Exit
   - Web-based control panel on port 5000
   - Flask backend for REST API

4. **Bot Lifecycle Management**
   - Centralized start/stop/restart control
   - Graceful shutdown with thread cleanup
   - Works on Windows, macOS, Linux
   - Restart spawns new process before exiting

5. **Directory Structure**
   src/
   ├── license/           # License validation (copy from guide)
   ├── gui/
   │   ├── splash_screen.py
   │   ├── license_controller.py
   │   └── system_tray.py
   ├── services/
   │   └── lifecycle_manager.py
   └── main.py            # Entry point
   gui_app/
   └── ...                # Flask web panel
   build/
   └── build_exe.spec     # PyInstaller config
```

---

## Project Structure

```
india-trading-bot/
├── .github/
│   └── workflows/
│       └── build-user.yml        # GitHub Actions workflow
├── build/
│   └── build_exe.spec            # PyInstaller spec (console=False)
├── src/
│   ├── license/                  # License system (7 files)
│   │   ├── __init__.py
│   │   ├── license_types.py
│   │   ├── crypto.py
│   │   ├── cache.py
│   │   ├── client.py
│   │   ├── heartbeat.py
│   │   └── network_monitor.py
│   ├── gui/                      # GUI components
│   │   ├── __init__.py
│   │   ├── splash_screen.py
│   │   ├── license_controller.py
│   │   └── system_tray.py
│   ├── services/
│   │   └── lifecycle_manager.py
│   └── main.py                   # Entry point
├── gui_app/                      # Flask web panel
│   ├── __init__.py
│   ├── app.py
│   └── routes.py
├── upgrade/
│   └── version.py
├── requirements.txt
└── README.md
```

---

## Complete Code Files

### 1. Entry Point - `src/main.py`

```python
"""
India Trading Bot - Main Entry Point
No console window, splash screen for license, background operation
"""
import os
import sys
import threading
from typing import Optional

# Set build type (changed by CI to USER or ADMIN)
BUILD_TYPE = 'DEV'

def main():
    """Main entry point with splash screen and license validation"""
    
    # Initialize Qt application FIRST (required for splash screen)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray
    app.setApplicationName("IndiaTradingBot")
    
    # Import components after Qt is initialized
    from src.gui.splash_screen import SplashScreen, StartupProgress
    from src.gui.system_tray import setup_system_tray, get_tray_manager
    from src.services.lifecycle_manager import get_lifecycle_manager
    
    # Create progress reporter for startup steps
    progress = StartupProgress()
    
    # Create and show splash screen
    splash = SplashScreen(progress_reporter=progress)
    splash.show()
    
    # Variables for startup state
    startup_state = {'license_valid': False, 'license_data': {}}
    
    def on_license_validated(license_data: dict):
        """Called when license is validated successfully"""
        startup_state['license_valid'] = True
        startup_state['license_data'] = license_data
        print(f"[MAIN] License validated: {license_data.get('days_remaining')} days remaining")
    
    def on_startup_ready():
        """Called when splash is done and we can start the bot"""
        if not startup_state['license_valid']:
            print("[MAIN] License not validated - cannot start")
            return
        
        # Start the actual bot components
        QTimer.singleShot(100, lambda: start_bot_components(app, splash, progress))
    
    # Connect splash signals
    splash.license_validated.connect(on_license_validated)
    splash.startup_ready.connect(on_startup_ready)
    
    # Start event loop
    sys.exit(app.exec())


def start_bot_components(app, splash, progress):
    """Start all bot components after license validation"""
    from src.gui.system_tray import setup_system_tray, get_tray_manager
    from src.services.lifecycle_manager import get_lifecycle_manager
    from src.license import start_network_monitor, start_license_heartbeat
    
    try:
        # Step 1: Initialize license monitoring
        progress.update(1, "Starting license monitor...")
        license_key = os.getenv('LICENSE_KEY', '')
        if license_key:
            start_network_monitor(license_key)
            start_license_heartbeat(license_key, interval_minutes=30)
        
        # Step 2: Setup system tray
        progress.update(2, "Setting up system tray...")
        tray = setup_system_tray()
        tray.set_status("starting", "Initializing...")
        
        # Step 3: Initialize database
        progress.update(3, "Initializing database...")
        try:
            from gui_app.database import init_db
            init_db()
        except ImportError:
            pass
        
        # Step 4: Start Flask web panel
        progress.update(4, "Starting control panel...")
        flask_thread = start_flask_server()
        
        # Step 5: Initialize broker connections
        progress.update(5, "Connecting to brokers...")
        # Add your broker initialization here
        
        # Step 6: Start Discord/Telegram bot
        progress.update(6, "Starting signal monitors...")
        discord_thread, discord_shutdown = start_discord_bot()
        telegram_thread, telegram_shutdown = start_telegram_bot()
        
        # Step 7: Register with lifecycle manager
        progress.update(7, "Registering services...")
        lifecycle = get_lifecycle_manager()
        lifecycle.register_threads(
            discord_thread=discord_thread,
            telegram_thread=telegram_thread,
            discord_shutdown=discord_shutdown,
            telegram_shutdown=telegram_shutdown,
            gui_port=5000
        )
        lifecycle.register_qt_app(app)
        
        # Step 8: Final setup
        progress.update(8, "Finalizing...")
        
        # Update tray status
        tray.set_status("running", "Monitoring signals")
        tray.show_notification(
            "India Trading Bot",
            "Bot is now running and monitoring for signals"
        )
        
        # Step 9: Complete startup
        progress.update(9, "Ready!")
        progress.complete()
        
        # Hide splash screen after brief delay
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, splash.close)
        
        print("[MAIN] Bot started successfully")
        
    except Exception as e:
        print(f"[MAIN] Startup error: {e}")
        import traceback
        traceback.print_exc()
        progress.fail(str(e))


def start_flask_server() -> threading.Thread:
    """Start Flask web control panel in background thread"""
    def run_flask():
        try:
            from gui_app.app import create_app
            app = create_app()
            app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
        except Exception as e:
            print(f"[FLASK] Error: {e}")
    
    thread = threading.Thread(target=run_flask, daemon=True, name="FlaskServer")
    thread.start()
    return thread


def start_discord_bot():
    """Start Discord bot - placeholder for your implementation"""
    shutdown_event = threading.Event()
    
    def run_discord():
        # Your Discord bot code here
        while not shutdown_event.is_set():
            shutdown_event.wait(1)
    
    thread = threading.Thread(target=run_discord, daemon=True, name="DiscordBot")
    thread.start()
    return thread, shutdown_event


def start_telegram_bot():
    """Start Telegram bot - placeholder for your implementation"""
    shutdown_event = threading.Event()
    
    def run_telegram():
        # Your Telegram bot code here
        while not shutdown_event.is_set():
            shutdown_event.wait(1)
    
    thread = threading.Thread(target=run_telegram, daemon=True, name="TelegramBot")
    thread.start()
    return thread, shutdown_event


if __name__ == '__main__':
    main()
```

### 2. Splash Screen - `src/gui/splash_screen.py`

```python
"""
India Trading Bot - Premium Splash Screen
Glassmorphism design with license validation and progress tracking
"""
import sys
import os
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QGraphicsDropShadowEffect, QStackedWidget,
    QLineEdit, QPushButton, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QColor

try:
    from upgrade.version import APP_VERSION
except ImportError:
    APP_VERSION = "1.0.0"

try:
    from .license_controller import LicenseController, LicenseState
except ImportError:
    LicenseController = None
    LicenseState = None


class StartupProgress(QObject):
    """Thread-safe progress reporter for startup sequence"""
    progress_updated = Signal(int, str)
    startup_complete = Signal()
    startup_failed = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._current_step = 0
        self._total_steps = 10
    
    def update(self, step: int, message: str):
        self._current_step = step
        percent = int((step / self._total_steps) * 100)
        self.progress_updated.emit(percent, message)
    
    def complete(self):
        self.startup_complete.emit()
    
    def fail(self, error: str):
        self.startup_failed.emit(error)


class SplashScreen(QWidget):
    """Premium splash screen with license validation"""
    
    license_validated = Signal(dict)
    license_required = Signal()
    startup_ready = Signal()
    
    def __init__(self, progress_reporter: Optional[StartupProgress] = None, skip_license: bool = False):
        super().__init__()
        self.progress_reporter = progress_reporter
        self.skip_license = skip_license
        self.license_controller = LicenseController() if LicenseController else None
        self._license_check_started = False
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the splash screen UI"""
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint |
            Qt.SplashScreen
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(520, 420)
        
        # Center on screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Main container with glassmorphism
        container = QWidget()
        container.setObjectName("splashContainer")
        container.setStyleSheet("""
            #splashContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 15, 30, 0.95), 
                    stop:0.3 rgba(20, 30, 60, 0.92),
                    stop:0.7 rgba(15, 25, 50, 0.92),
                    stop:1 rgba(8, 12, 25, 0.95));
                border-radius: 20px;
                border: 1px solid rgba(79, 172, 254, 0.4);
            }
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(50)
        shadow.setColor(QColor(79, 172, 254, 80))
        shadow.setOffset(0, 8)
        container.setGraphicsEffect(shadow)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(40, 35, 40, 30)
        container_layout.setSpacing(12)
        
        # Header with logo
        header_layout = QHBoxLayout()
        header_layout.setSpacing(18)
        header_layout.setAlignment(Qt.AlignCenter)
        
        logo = QLabel("IT")  # India Trader
        logo.setFixedSize(72, 72)
        logo.setAlignment(Qt.AlignCenter)
        logo.setFont(QFont("Segoe UI", 28, QFont.Bold))
        logo.setStyleSheet("""
            color: #48bb78;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(72, 187, 120, 0.25),
                stop:1 rgba(72, 187, 120, 0.25));
            border-radius: 18px;
            border: 1px solid rgba(72, 187, 120, 0.4);
        """)
        header_layout.addWidget(logo)
        
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        
        title = QLabel("India Trader")
        title.setFont(QFont("Segoe UI", 32, QFont.Bold))
        title.setStyleSheet("color: #48bb78; background: transparent;")
        title_layout.addWidget(title)
        
        subtitle = QLabel("NSE/BSE/MCX Trading Automation")
        subtitle.setFont(QFont("Segoe UI", 11))
        subtitle.setStyleSheet("color: rgba(136, 146, 176, 0.9); background: transparent;")
        title_layout.addWidget(subtitle)
        
        header_layout.addWidget(title_container)
        container_layout.addLayout(header_layout)
        container_layout.addSpacing(20)
        
        # Stacked widget for license/progress panels
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("background: transparent;")
        
        self._create_license_panel()
        self._create_progress_panel()
        self.stacked_widget.setCurrentIndex(1)  # Start with progress
        
        container_layout.addWidget(self.stacked_widget)
        container_layout.addStretch()
        
        # Footer
        footer_layout = QHBoxLayout()
        copyright = QLabel("India Market Trading Platform")
        copyright.setFont(QFont("Segoe UI", 9))
        copyright.setStyleSheet("color: rgba(74, 85, 104, 0.7); background: transparent;")
        footer_layout.addWidget(copyright)
        footer_layout.addStretch()
        
        version = QLabel(f"v{APP_VERSION}")
        version.setFont(QFont("Segoe UI Semibold", 9))
        version.setStyleSheet("""
            color: rgba(72, 187, 120, 0.8);
            background: rgba(72, 187, 120, 0.1);
            padding: 4px 10px;
            border-radius: 10px;
        """)
        footer_layout.addWidget(version)
        
        container_layout.addLayout(footer_layout)
        main_layout.addWidget(container)
    
    def _create_license_panel(self):
        """Create license activation panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        glass = QFrame()
        glass.setStyleSheet("""
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        """)
        glass_layout = QVBoxLayout(glass)
        glass_layout.setContentsMargins(20, 18, 20, 18)
        glass_layout.setSpacing(12)
        
        self.license_title = QLabel("License Activation")
        self.license_title.setFont(QFont("Segoe UI Semibold", 13))
        self.license_title.setAlignment(Qt.AlignCenter)
        self.license_title.setStyleSheet("color: #48bb78; background: transparent;")
        glass_layout.addWidget(self.license_title)
        
        self.license_message = QLabel("Enter your license key or start a free trial")
        self.license_message.setFont(QFont("Segoe UI", 10))
        self.license_message.setAlignment(Qt.AlignCenter)
        self.license_message.setWordWrap(True)
        self.license_message.setStyleSheet("color: #a0aec0; background: transparent;")
        glass_layout.addWidget(self.license_message)
        
        self.license_input = QLineEdit()
        self.license_input.setPlaceholderText("Enter license key (IT-XXXX-XXXX-XXXX)")
        self.license_input.setFont(QFont("Consolas", 11))
        self.license_input.setAlignment(Qt.AlignCenter)
        self.license_input.setFixedHeight(42)
        self.license_input.setStyleSheet("""
            QLineEdit {
                background: rgba(45, 55, 72, 0.6);
                border: 1px solid rgba(72, 187, 120, 0.3);
                border-radius: 8px;
                color: #e2e8f0;
                padding: 8px 15px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(72, 187, 120, 0.7);
            }
        """)
        glass_layout.addWidget(self.license_input)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.trial_button = QPushButton("Start Free Trial")
        self.trial_button.setFont(QFont("Segoe UI Semibold", 10))
        self.trial_button.setFixedHeight(38)
        self.trial_button.setCursor(Qt.PointingHandCursor)
        self.trial_button.setStyleSheet("""
            QPushButton {
                background: rgba(72, 187, 120, 0.2);
                border: 1px solid rgba(72, 187, 120, 0.5);
                border-radius: 8px;
                color: #48bb78;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: rgba(72, 187, 120, 0.3);
            }
            QPushButton:disabled {
                background: rgba(45, 55, 72, 0.4);
                color: rgba(160, 174, 192, 0.5);
            }
        """)
        btn_layout.addWidget(self.trial_button)
        
        self.activate_button = QPushButton("Activate License")
        self.activate_button.setFont(QFont("Segoe UI Semibold", 10))
        self.activate_button.setFixedHeight(38)
        self.activate_button.setCursor(Qt.PointingHandCursor)
        self.activate_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(72, 187, 120, 0.3), stop:1 rgba(56, 178, 172, 0.3));
                border: 1px solid rgba(72, 187, 120, 0.5);
                border-radius: 8px;
                color: #48bb78;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(72, 187, 120, 0.4), stop:1 rgba(56, 178, 172, 0.4));
            }
            QPushButton:disabled {
                background: rgba(45, 55, 72, 0.4);
                color: rgba(160, 174, 192, 0.5);
            }
        """)
        btn_layout.addWidget(self.activate_button)
        
        glass_layout.addLayout(btn_layout)
        
        self.license_status = QLabel("")
        self.license_status.setFont(QFont("Segoe UI", 9))
        self.license_status.setAlignment(Qt.AlignCenter)
        self.license_status.setWordWrap(True)
        self.license_status.setStyleSheet("color: #fc8181; background: transparent;")
        self.license_status.hide()
        glass_layout.addWidget(self.license_status)
        
        layout.addWidget(glass)
        self.stacked_widget.addWidget(panel)
    
    def _create_progress_panel(self):
        """Create startup progress panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        
        glass = QFrame()
        glass.setStyleSheet("""
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        """)
        glass_layout = QVBoxLayout(glass)
        glass_layout.setContentsMargins(20, 18, 20, 18)
        glass_layout.setSpacing(12)
        
        self.license_info = QLabel("")
        self.license_info.setFont(QFont("Segoe UI", 10))
        self.license_info.setAlignment(Qt.AlignCenter)
        self.license_info.setStyleSheet("color: #48bb78; background: transparent;")
        glass_layout.addWidget(self.license_info)
        
        self.status_label = QLabel("Initializing...")
        self.status_label.setFont(QFont("Segoe UI", 11))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #e2e8f0; background: transparent;")
        glass_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(45, 55, 72, 0.6);
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #48bb78, stop:0.5 #38b2ac, stop:1 #48bb78);
                border-radius: 3px;
            }
        """)
        glass_layout.addWidget(self.progress_bar)
        
        layout.addWidget(glass)
        self.stacked_widget.addWidget(panel)
    
    def _connect_signals(self):
        """Connect UI signals"""
        self.trial_button.clicked.connect(self._on_trial_clicked)
        self.activate_button.clicked.connect(self._on_activate_clicked)
        self.license_input.returnPressed.connect(self._on_activate_clicked)
        
        if self.license_controller:
            self.license_controller.state_changed.connect(self._on_license_state_changed)
            self.license_controller.license_activated.connect(self._on_license_activated)
            self.license_controller.license_failed.connect(self._on_license_failed)
            self.license_controller.require_input.connect(self._on_require_input)
        
        if self.progress_reporter:
            self.progress_reporter.progress_updated.connect(self._on_progress_update)
            self.progress_reporter.startup_complete.connect(self._on_startup_complete)
            self.progress_reporter.startup_failed.connect(self._on_startup_failed)
    
    def showEvent(self, event):
        """Called when splash is shown - trigger license check"""
        super().showEvent(event)
        if not self._license_check_started:
            self._license_check_started = True
            QTimer.singleShot(50, self._auto_license_check)
    
    def _auto_license_check(self):
        """Check for existing license"""
        if self.skip_license:
            self.status_label.setText("License verified - starting...")
            QTimer.singleShot(0, self.startup_ready.emit)
            return
        
        self.status_label.setText("Checking license...")
        QApplication.processEvents()
        
        if self.license_controller:
            self.license_controller.check_existing_license()
        else:
            license_key = os.getenv('LICENSE_KEY', '').strip()
            if license_key:
                self.license_info.setText("License: Active")
                self.status_label.setText("Starting...")
                QTimer.singleShot(0, self.startup_ready.emit)
            else:
                self._show_license_panel()
    
    def _show_license_panel(self):
        self.stacked_widget.setCurrentIndex(0)
        self.setFixedSize(520, 420)
    
    def _show_progress_panel(self):
        self.stacked_widget.setCurrentIndex(1)
        self.setFixedSize(520, 340)
    
    def _on_trial_clicked(self):
        if self.license_controller:
            self._show_validating()
            self.license_controller.request_trial()
        else:
            self.license_status.setText("Trial not available")
            self.license_status.show()
    
    def _on_activate_clicked(self):
        license_key = self.license_input.text().strip()
        if not license_key:
            self.license_status.setText("Please enter a license key")
            self.license_status.show()
            return
        
        if self.license_controller:
            self._show_validating()
            self.license_controller.activate_license(license_key)
        else:
            os.environ['LICENSE_KEY'] = license_key
            self._on_license_activated({'days_remaining': 365, 'license_type': 'manual'})
    
    def _show_validating(self):
        self.license_message.setText("Validating license...")
        self.license_input.setEnabled(False)
        self.trial_button.setEnabled(False)
        self.activate_button.setEnabled(False)
        self.license_status.hide()
    
    def _on_license_state_changed(self, state, message: str):
        if state == LicenseState.VALIDATING:
            self.status_label.setText("Validating license...")
        elif state in (LicenseState.ACTIVATED, LicenseState.OFFLINE_GRACE):
            self.status_label.setText("License valid - starting...")
        elif state == LicenseState.REQUIRE_KEY:
            self._show_license_panel()
            self.license_input.setEnabled(True)
            self.trial_button.setEnabled(True)
            self.activate_button.setEnabled(True)
            if message:
                self.license_status.setText(message)
                self.license_status.show()
        elif state == LicenseState.EXPIRED:
            self._show_license_panel()
            self.license_title.setText("License Expired")
            self.license_title.setStyleSheet("color: #fc8181; background: transparent;")
            self.license_message.setText("Please renew or enter a new key.")
            self.trial_button.setEnabled(False)
    
    def _on_license_activated(self, license_data: dict):
        days = license_data.get('days_remaining', 0)
        license_type = license_data.get('license_type', 'subscription').title()
        
        self.license_info.setText(f"{license_type} License - {days} days remaining")
        self._show_progress_panel()
        self.license_validated.emit(license_data)
        self.startup_ready.emit()
    
    def _on_license_failed(self, error: str):
        self.license_status.setText(error)
        self.license_status.show()
        self.license_input.setEnabled(True)
        self.trial_button.setEnabled(True)
        self.activate_button.setEnabled(True)
    
    def _on_require_input(self, message: str):
        self._show_license_panel()
        if message:
            self.license_status.setText(message)
            self.license_status.show()
    
    def _on_progress_update(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)
    
    def _on_startup_complete(self):
        self.progress_bar.setValue(100)
        self.status_label.setText("Ready!")
    
    def _on_startup_failed(self, error: str):
        self.status_label.setText(f"Error: {error}")
        self.status_label.setStyleSheet("color: #fc8181; background: transparent;")
```

### 3. License Controller - `src/gui/license_controller.py`

```python
"""
License Controller - State machine for license validation flow
"""
from enum import Enum, auto
from typing import Optional, Dict
from PySide6.QtCore import QObject, Signal, QThread
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from license.client import LicenseClient
except ImportError:
    try:
        from src.license.client import LicenseClient
    except ImportError:
        LicenseClient = None


class LicenseState(Enum):
    INIT = auto()
    VALIDATING = auto()
    ACTIVATED = auto()
    REQUIRE_KEY = auto()
    EXPIRED = auto()
    OFFLINE_GRACE = auto()
    FAILED = auto()


class LicenseValidationWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, client, license_key: Optional[str] = None, action: str = 'validate'):
        super().__init__()
        self.client = client
        self.license_key = license_key
        self.action = action
    
    def run(self):
        try:
            if self.action == 'validate':
                result = self.client.validate_license(self.license_key)
            elif self.action == 'activate':
                result = self.client.activate_license(self.license_key)
            elif self.action == 'trial':
                result = self.client.request_trial()
            else:
                result = {'success': False, 'error': f'Unknown action: {self.action}'}
            
            self.finished.emit(result if isinstance(result, dict) else result[1])
        except Exception as e:
            self.error.emit(str(e))


class LicenseController(QObject):
    state_changed = Signal(LicenseState, str)
    validation_progress = Signal(str)
    license_activated = Signal(dict)
    license_failed = Signal(str)
    require_input = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._state = LicenseState.INIT
        self._license_data: Dict = {}
        self._worker: Optional[LicenseValidationWorker] = None
        self._client = LicenseClient() if LicenseClient else None
    
    def check_existing_license(self) -> bool:
        """Check for existing valid license"""
        if not self._client:
            license_key = os.getenv('LICENSE_KEY', '').strip()
            if license_key:
                self._license_data = {'is_valid': True, 'days_remaining': 365}
                self._set_state(LicenseState.ACTIVATED, "License activated")
                self.license_activated.emit(self._license_data)
                return True
            self._set_state(LicenseState.REQUIRE_KEY, "Please enter your license key")
            self.require_input.emit("No license found.")
            return False
        
        self._set_state(LicenseState.VALIDATING, "Checking license...")
        
        # Check cache
        cached = None
        try:
            cached = self._client._cache.load()
        except:
            pass
        
        license_key = None
        if cached:
            license_key = cached.get('license_key')
        if not license_key:
            license_key = os.getenv('LICENSE_KEY', '').strip()
        
        if license_key:
            self._start_validation(license_key, 'validate')
            return True
        
        self._set_state(LicenseState.REQUIRE_KEY, "Please enter your license key")
        self.require_input.emit("No license found.")
        return False
    
    def _set_state(self, state: LicenseState, message: str = ""):
        self._state = state
        self.state_changed.emit(state, message)
    
    def _start_validation(self, license_key: str, action: str):
        self._set_state(LicenseState.VALIDATING, "Validating license...")
        self._worker = LicenseValidationWorker(self._client, license_key, action)
        self._worker.finished.connect(self._on_validation_complete)
        self._worker.error.connect(self._on_validation_error)
        self._worker.start()
    
    def _on_validation_complete(self, result: Dict):
        is_valid = result.get('success') or result.get('is_valid') or (isinstance(result, tuple) and result[0])
        
        if is_valid:
            self._license_data = result
            days = result.get('days_remaining', 0)
            if days <= 0:
                self._set_state(LicenseState.EXPIRED, "License expired")
                self.require_input.emit("License expired.")
            else:
                self._set_state(LicenseState.ACTIVATED, f"License valid ({days} days)")
                self.license_activated.emit(result)
        elif result.get('offline'):
            self._set_state(LicenseState.REQUIRE_KEY, "Offline - please connect")
            self.require_input.emit("Cannot validate offline.")
        else:
            error = result.get('error', 'Validation failed')
            self._set_state(LicenseState.REQUIRE_KEY, error)
            self.require_input.emit(error)
    
    def _on_validation_error(self, error: str):
        self._set_state(LicenseState.FAILED, error)
        self.license_failed.emit(error)
    
    def activate_license(self, license_key: str):
        if not license_key.strip():
            self._set_state(LicenseState.REQUIRE_KEY, "Please enter a valid key")
            return
        
        license_key = license_key.strip().upper()
        
        if not self._client:
            os.environ['LICENSE_KEY'] = license_key
            self._license_data = {'is_valid': True, 'days_remaining': 365, 'license_key': license_key}
            self._set_state(LicenseState.ACTIVATED, "License activated")
            self.license_activated.emit(self._license_data)
            return
        
        self._start_validation(license_key, 'activate')
    
    def request_trial(self):
        if not self._client:
            self._set_state(LicenseState.FAILED, "Trial requires internet")
            self.license_failed.emit("Trial requires internet")
            return
        
        self._set_state(LicenseState.VALIDATING, "Activating trial...")
        self._start_validation('', 'trial')
```

### 4. System Tray - `src/gui/system_tray.py`

```python
"""
India Trading Bot - System Tray Icon
Background operation with tray-based control
"""
import sys
import os
import webbrowser
import threading
from typing import Optional
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction


class TrayIconManager(QObject):
    show_logs_requested = Signal()
    restart_requested = Signal()
    shutdown_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.menu: Optional[QMenu] = None
        self.web_panel_port = 5000
        self._status = "starting"
        self._setup_tray()
    
    def _create_icon(self, status: str = "running") -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        colors = {
            "running": QColor("#22c55e"),
            "starting": QColor("#f59e0b"),
            "error": QColor("#ef4444")
        }
        color = colors.get(status, QColor("#6b7280"))
        
        painter.setBrush(QColor("#1a1a2e"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
        
        painter.setBrush(color)
        painter.drawEllipse(22, 22, 20, 20)
        
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "IT")
        
        painter.end()
        return QIcon(pixmap)
    
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        self.tray_icon = QSystemTrayIcon(self._create_icon("starting"))
        self.tray_icon.setToolTip("India Trading Bot - Starting...")
        
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a2e;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 8px;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2d3748;
            }
            QMenu::separator {
                height: 1px;
                background: #4a5568;
                margin: 5px 10px;
            }
        """)
        
        self.status_action = QAction("Status: Starting...", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        
        self.menu.addSeparator()
        
        open_panel = QAction("Open Control Panel", self.menu)
        open_panel.triggered.connect(self._open_web_panel)
        self.menu.addAction(open_panel)
        
        self.menu.addSeparator()
        
        restart = QAction("Restart Bot", self.menu)
        restart.triggered.connect(self._on_restart)
        self.menu.addAction(restart)
        
        self.menu.addSeparator()
        
        exit_action = QAction("Exit", self.menu)
        exit_action.triggered.connect(self._on_exit)
        self.menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_activated)
    
    def show(self):
        if self.tray_icon:
            self.tray_icon.show()
    
    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()
    
    def set_status(self, status: str, message: str = ""):
        self._status = status
        if self.tray_icon:
            self.tray_icon.setIcon(self._create_icon(status))
            status_text = {"running": "Running", "starting": "Starting...", "error": "Error", "stopped": "Stopped"}.get(status, status.title())
            tooltip = f"India Trading Bot - {status_text}"
            if message:
                tooltip += f"\n{message}"
            self.tray_icon.setToolTip(tooltip)
            if self.status_action:
                self.status_action.setText(f"Status: {status_text}")
    
    def show_notification(self, title: str, message: str, duration_ms: int = 5000):
        if self.tray_icon and self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, duration_ms)
    
    def _open_web_panel(self):
        webbrowser.open(f"http://localhost:{self.web_panel_port}")
    
    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._open_web_panel()
    
    def _on_restart(self):
        reply = QMessageBox.question(None, "Restart Bot", "Are you sure you want to restart?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.restart_requested.emit()
            self.set_status("starting", "Restarting...")
            try:
                from src.services.lifecycle_manager import get_lifecycle_manager
                threading.Thread(target=get_lifecycle_manager().restart, daemon=True).start()
            except ImportError:
                pass
    
    def _on_exit(self):
        reply = QMessageBox.question(None, "Exit", "Are you sure you want to exit?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.shutdown_requested.emit()
            if self.tray_icon:
                self.tray_icon.hide()
            try:
                from src.services.lifecycle_manager import get_lifecycle_manager
                threading.Thread(target=lambda: get_lifecycle_manager().exit(0), daemon=True).start()
            except ImportError:
                QApplication.quit()


_tray_manager: Optional[TrayIconManager] = None


def get_tray_manager() -> TrayIconManager:
    global _tray_manager
    if _tray_manager is None:
        _tray_manager = TrayIconManager()
    return _tray_manager


def setup_system_tray() -> TrayIconManager:
    tray = get_tray_manager()
    tray.show()
    return tray
```

### 5. Lifecycle Manager - `src/services/lifecycle_manager.py`

```python
"""
India Trading Bot - Lifecycle Manager
Centralized control for start/stop/restart
"""
import os
import sys
import threading
import time
from typing import Optional, Callable, Dict, Any
from enum import Enum


class BotState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    ERROR = "error"


class BotLifecycleManager:
    _instance: Optional['BotLifecycleManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._state = BotState.STOPPED
        self._state_lock = threading.Lock()
        self._discord_thread: Optional[threading.Thread] = None
        self._telegram_thread: Optional[threading.Thread] = None
        self._discord_shutdown: Optional[threading.Event] = None
        self._telegram_shutdown: Optional[threading.Event] = None
        self._gui_port: int = 5000
        self._qt_app = None
        self._on_state_change_callbacks: list = []
        self._shutdown_in_progress = False
    
    @property
    def state(self) -> BotState:
        with self._state_lock:
            return self._state
    
    @state.setter
    def state(self, new_state: BotState):
        with self._state_lock:
            old_state = self._state
            self._state = new_state
        if old_state != new_state:
            for cb in self._on_state_change_callbacks:
                try:
                    cb(new_state)
                except:
                    pass
    
    def on_state_change(self, callback: Callable[[BotState], None]):
        self._on_state_change_callbacks.append(callback)
    
    def register_threads(self, discord_thread=None, telegram_thread=None, discord_shutdown=None, telegram_shutdown=None, gui_port=5000):
        self._discord_thread = discord_thread
        self._telegram_thread = telegram_thread
        self._discord_shutdown = discord_shutdown
        self._telegram_shutdown = telegram_shutdown
        self._gui_port = gui_port
        self.state = BotState.RUNNING
    
    def register_qt_app(self, app):
        self._qt_app = app
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'state': self.state.value,
            'discord_running': self._discord_thread.is_alive() if self._discord_thread else False,
            'telegram_running': self._telegram_thread.is_alive() if self._telegram_thread else False,
            'gui_port': self._gui_port,
            'shutdown_in_progress': self._shutdown_in_progress
        }
    
    def stop(self, force: bool = False) -> bool:
        if self._shutdown_in_progress:
            return False
        
        self._shutdown_in_progress = True
        self.state = BotState.STOPPING
        print("[LIFECYCLE] Stopping...")
        
        try:
            if self._discord_shutdown:
                self._discord_shutdown.set()
            if self._telegram_shutdown:
                self._telegram_shutdown.set()
            
            timeout = 3 if force else 10
            
            if self._discord_thread and self._discord_thread.is_alive():
                self._discord_thread.join(timeout=timeout)
            if self._telegram_thread and self._telegram_thread.is_alive():
                self._telegram_thread.join(timeout=timeout)
            
            self.state = BotState.STOPPED
            
            if self._qt_app:
                self._qt_app.quit()
            
            return True
        except Exception as e:
            print(f"[LIFECYCLE] Error: {e}")
            self.state = BotState.ERROR
            return False
        finally:
            self._shutdown_in_progress = False
    
    def exit(self, exit_code: int = 0):
        print("[LIFECYCLE] Exiting...")
        self.stop(force=True)
        time.sleep(0.5)
        os._exit(exit_code)
    
    def restart(self) -> bool:
        self.state = BotState.RESTARTING
        print("[LIFECYCLE] Restarting...")
        
        try:
            self.stop(force=True)
            
            import subprocess
            import tempfile
            
            if hasattr(sys, '_MEIPASS'):
                exe_path = sys.executable
                
                if sys.platform == 'win32':
                    batch = f'''@echo off
timeout /t 2 /nobreak >nul
start "" "{exe_path}"
del "%~f0"
'''
                    batch_path = os.path.join(tempfile.gettempdir(), f"restart_{os.getpid()}.bat")
                    with open(batch_path, 'w') as f:
                        f.write(batch)
                    
                    subprocess.Popen(['cmd', '/c', batch_path],
                        creationflags=0x08000000 | 0x00000008,
                        close_fds=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(['bash', '-c', f'sleep 2 && "{exe_path}"'],
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
            else:
                python_exe = sys.executable
                script = os.path.abspath(sys.argv[0])
                subprocess.Popen([python_exe, script],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=os.path.dirname(script) or '.')
                time.sleep(1)
            
            os._exit(0)
            
        except Exception as e:
            print(f"[LIFECYCLE] Restart failed: {e}")
            self.state = BotState.ERROR
            return False
        
        return True


_lifecycle_manager: Optional[BotLifecycleManager] = None


def get_lifecycle_manager() -> BotLifecycleManager:
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = BotLifecycleManager()
    return _lifecycle_manager
```

### 6. GUI Package Init - `src/gui/__init__.py`

```python
"""India Trading Bot GUI Components"""
from .splash_screen import SplashScreen, StartupProgress
from .license_controller import LicenseController, LicenseState
from .system_tray import TrayIconManager, get_tray_manager, setup_system_tray

__all__ = [
    'SplashScreen', 'StartupProgress',
    'LicenseController', 'LicenseState',
    'TrayIconManager', 'get_tray_manager', 'setup_system_tray'
]
```

### 7. PyInstaller Spec - `build/build_exe.spec`

```python
# PyInstaller spec for India Trading Bot
# console=False for GUI-only operation

import os
import glob
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# Collect broker submodules
upstox_imports = collect_submodules('upstox_client') if __import__('importlib').util.find_spec('upstox_client') else []
dhanhq_imports = collect_submodules('dhanhq') if __import__('importlib').util.find_spec('dhanhq') else []
kiteconnect_imports = collect_submodules('kiteconnect') if __import__('importlib').util.find_spec('kiteconnect') else []

# Find PyArmor runtime
pyarmor_runtime_data = []
pyarmor_hidden = []
for pattern in ['src/pyarmor_runtime_*', 'pyarmor_runtime_*']:
    for runtime_dir in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
        if os.path.isdir(runtime_dir):
            runtime_name = os.path.basename(runtime_dir)
            pyarmor_runtime_data.append((runtime_dir, runtime_name))
            pyarmor_hidden.append(runtime_name)

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'src', 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'src'), 'src'),
        (os.path.join(PROJECT_ROOT, 'gui_app'), 'gui_app'),
        (os.path.join(PROJECT_ROOT, 'upgrade'), 'upgrade'),
    ] + pyarmor_runtime_data,
    hiddenimports=upstox_imports + dhanhq_imports + kiteconnect_imports + pyarmor_hidden + [
        'PySide6', 'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
        'flask', 'jinja2', 'werkzeug',
        'cryptography', 'cryptography.fernet',
        'requests', 'aiohttp', 'httpx',
        'telethon',
        'json', 'asyncio', 'threading', 'logging',
        'src.gui', 'src.gui.splash_screen', 'src.gui.system_tray',
        'src.gui.license_controller',
        'src.services.lifecycle_manager',
        'src.license', 'src.license.client',
        'gui_app', 'gui_app.app',
    ],
    hookspath=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IndiaTradingBot',
    debug=False,
    strip=False,
    upx=True,
    console=False,  # NO CONSOLE - GUI only
)

print("[BUILD] Complete - IndiaTradingBot built with console=False")
```

### 8. Requirements - `requirements.txt`

```
PySide6>=6.5.0
flask>=2.0.0
requests>=2.28.0
cryptography>=41.0.0
aiohttp>=3.8.0
telethon>=1.28.0
upstox-python-sdk>=2.0.0
dhanhq>=1.0.0
kiteconnect>=4.0.0
```

---

## Startup Flow

```
User double-clicks .exe
       │
       ▼
┌─────────────────────────┐
│   NO CONSOLE WINDOW     │
│   (console=False)       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│    SPLASH SCREEN        │
│  "Checking license..."  │
└───────────┬─────────────┘
            │
            ▼
       Has license?
      /          \
    Yes           No
     │             │
     ▼             ▼
┌──────────┐  ┌──────────────────┐
│ Validate │  │ Show License     │
│ Online   │  │ Entry Panel      │
└────┬─────┘  │ - Enter key      │
     │        │ - Start Trial    │
     ▼        └────────┬─────────┘
 Valid?                │
   │                   ▼
   Yes            Activate/Trial
   │                   │
   ▼                   ▼
┌─────────────────────────┐
│  PROGRESS PANEL         │
│  "Starting services..." │
│  [=========>           ]│
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   SPLASH CLOSES         │
│   TRAY ICON APPEARS     │
│   (green = running)     │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  BACKGROUND OPERATION   │
│  - Discord monitoring   │
│  - Telegram monitoring  │
│  - Web panel :5000      │
│  - License heartbeat    │
└─────────────────────────┘

TRAY MENU:
├── Status: Running
├── ─────────────────
├── Open Control Panel (browser)
├── ─────────────────
├── Restart Bot
├── ─────────────────
└── Exit
```

---

## Key Points

1. **console=False** in PyInstaller spec = no black console window
2. **Splash screen** appears first with license validation
3. **Trial button** requests trial from license server
4. **System tray** icon shows status (green/yellow/red)
5. **Tray menu** has Open Panel, Restart, Exit
6. **Lifecycle manager** handles clean restart/shutdown
7. **Same license server** as BotifyTrades

Copy all these files to your India project and run the GitHub Actions workflow to build the distributable.
