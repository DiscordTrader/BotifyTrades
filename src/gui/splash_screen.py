"""
BotifyTrades Premium Splash Screen
Modern glassmorphism design with integrated license validation and progress tracking
"""
import sys
import os
import platform
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QGraphicsDropShadowEffect, QStackedWidget,
    QLineEdit, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint, QEvent
from PySide6.QtGui import QFont, QColor, QAction, QKeySequence, QShortcut

try:
    from upgrade.version import APP_VERSION
except ImportError:
    APP_VERSION = "3.2.14"

try:
    from .license_controller import LicenseController, LicenseState
except ImportError:
    try:
        from license_controller import LicenseController, LicenseState
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
        """Update progress from any thread"""
        self._current_step = step
        percent = int((step / self._total_steps) * 100)
        self.progress_updated.emit(percent, message)
    
    def complete(self):
        """Signal that startup is complete"""
        self.startup_complete.emit()
    
    def fail(self, error: str):
        """Signal startup failure"""
        self.startup_failed.emit(error)


class _WindowControlButton(QPushButton):
    """macOS-style traffic light window control button"""
    
    def __init__(self, color: str, hover_color: str, icon_text: str = "", parent=None):
        super().__init__(parent)
        self._color = color
        self._hover_color = hover_color
        self._icon_text = icon_text
        self.setFixedSize(14, 14)
        self.setCursor(Qt.PointingHandCursor)
        self._update_style(hovered=False)
    
    def _update_style(self, hovered=False):
        bg = self._hover_color if hovered else self._color
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: none;
                border-radius: 7px;
                font-size: 8px;
                color: rgba(0,0,0,0.6);
                padding: 0;
                margin: 0;
            }}
        """)
        self.setText(self._icon_text if hovered else "")
    
    def enterEvent(self, event):
        self._update_style(hovered=True)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        self._update_style(hovered=False)
        super().leaveEvent(event)


class SplashScreen(QWidget):
    """
    Premium splash screen with glassmorphism design, license validation, and startup progress.
    Features: draggable window, close/minimize controls, full clipboard support.
    """
    
    license_validated = Signal(dict)
    license_required = Signal()
    startup_ready = Signal()
    
    def __init__(self, progress_reporter: Optional[StartupProgress] = None, skip_license: bool = False):
        super().__init__()
        self.progress_reporter = progress_reporter
        self.skip_license = skip_license
        self.license_controller = LicenseController() if LicenseController else None
        self._license_check_started = False
        self.license_rejected = False
        self.license_validated_ok = False  # set True only on successful activation
        self._drag_pos = None
        self._setup_ui()
        self._connect_signals()
        self._setup_shortcuts()

    def closeEvent(self, event):
        """SECURITY: If the user closes the splash window (X / ESC / Ctrl+Q) before
        license activation succeeded, mark as rejected so the startup watchdog
        refuses to launch the bot. Without this, closing the splash silently
        bypassed license enforcement after the 60s watchdog timer."""
        try:
            if not self.skip_license and not self.license_validated_ok:
                self.license_rejected = True
        except Exception:
            self.license_rejected = True
        super().closeEvent(event)
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts for clipboard operations and window management"""
        is_mac = platform.system() == 'Darwin'
        mod = Qt.ControlModifier if not is_mac else Qt.MetaModifier

        self._shortcuts = []
        for key, handler in [
            (Qt.Key_C, self._copy_selection),
            (Qt.Key_V, self._paste_clipboard),
            (Qt.Key_X, self._cut_selection),
            (Qt.Key_A, self._select_all),
            (Qt.Key_Q, self.close),
        ]:
            sc = QShortcut(QKeySequence(mod | key), self)
            sc.activated.connect(handler)
            self._shortcuts.append(sc)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.activated.connect(self.close)
        self._shortcuts.append(esc)

    def _copy_selection(self):
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit) and w.hasSelectedText():
            QApplication.clipboard().setText(w.selectedText())

    def _paste_clipboard(self):
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit):
            w.insert(QApplication.clipboard().text())

    def _cut_selection(self):
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit) and w.hasSelectedText():
            QApplication.clipboard().setText(w.selectedText())
            w.del_()

    def _select_all(self):
        w = QApplication.focusWidget()
        if isinstance(w, QLineEdit):
            w.selectAll()

    def _setup_ui(self):
        """Setup the splash screen UI with premium glassmorphism design"""
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Window
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.setFixedSize(540, 440)
        
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.geometry()
            x = (screen_geometry.width() - self.width()) // 2
            y = (screen_geometry.height() - self.height()) // 2
            self.move(x, y)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        container = QWidget()
        container.setObjectName("splashContainer")
        container.setStyleSheet("""
            #splashContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(10, 15, 30, 0.97), 
                    stop:0.3 rgba(20, 30, 60, 0.95),
                    stop:0.7 rgba(15, 25, 50, 0.95),
                    stop:1 rgba(8, 12, 25, 0.97));
                border-radius: 20px;
                border: 1px solid rgba(79, 172, 254, 0.35);
            }
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(50)
        shadow.setColor(QColor(79, 172, 254, 80))
        shadow.setOffset(0, 8)
        container.setGraphicsEffect(shadow)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("""
            #titleBar {
                background: transparent;
                border-top-left-radius: 20px;
                border-top-right-radius: 20px;
            }
        """)
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(16, 10, 16, 0)
        title_bar_layout.setSpacing(8)
        
        self._close_btn = _WindowControlButton("#ff5f57", "#ff3b30", "\u2715")
        self._close_btn.setToolTip("Close")
        self._close_btn.clicked.connect(self.close)
        title_bar_layout.addWidget(self._close_btn)
        
        self._minimize_btn = _WindowControlButton("#febc2e", "#f0a500", "\u2013")
        self._minimize_btn.setToolTip("Minimize")
        self._minimize_btn.clicked.connect(self.showMinimized)
        title_bar_layout.addWidget(self._minimize_btn)
        
        spacer_dot = QWidget()
        spacer_dot.setFixedSize(14, 14)
        spacer_dot.setStyleSheet("background: rgba(40, 50, 70, 0.5); border-radius: 7px;")
        title_bar_layout.addWidget(spacer_dot)
        
        title_bar_layout.addStretch()
        
        container_layout.addWidget(title_bar)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(40, 10, 40, 30)
        content_layout.setSpacing(12)
        
        header_layout = QHBoxLayout()
        header_layout.setSpacing(18)
        header_layout.setAlignment(Qt.AlignCenter)
        
        self.logo_label = QLabel("BT")
        self.logo_label.setFixedSize(72, 72)
        self.logo_label.setAlignment(Qt.AlignCenter)
        logo_font = QFont("Segoe UI", 28, QFont.Bold)
        self.logo_label.setFont(logo_font)
        self.logo_label.setStyleSheet("""
            color: #4facfe;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(79, 172, 254, 0.25),
                stop:0.5 rgba(0, 242, 254, 0.15),
                stop:1 rgba(79, 172, 254, 0.25));
            border-radius: 18px;
            border: 1px solid rgba(79, 172, 254, 0.4);
        """)
        
        logo_shadow = QGraphicsDropShadowEffect()
        logo_shadow.setBlurRadius(25)
        logo_shadow.setColor(QColor(79, 172, 254, 100))
        logo_shadow.setOffset(0, 4)
        self.logo_label.setGraphicsEffect(logo_shadow)
        
        header_layout.addWidget(self.logo_label)
        
        title_container = QWidget()
        title_vlayout = QVBoxLayout(title_container)
        title_vlayout.setContentsMargins(0, 0, 0, 0)
        title_vlayout.setSpacing(4)
        
        title_label = QLabel("BotifyTrades")
        title_label.setFont(QFont("Segoe UI", 32, QFont.Bold))
        title_label.setStyleSheet("color: #4facfe; background: transparent; letter-spacing: -1px;")
        title_vlayout.addWidget(title_label)
        
        subtitle_label = QLabel("Multi-Platform Trading Automation")
        subtitle_label.setFont(QFont("Segoe UI", 11, QFont.Normal))
        subtitle_label.setStyleSheet("color: rgba(136, 146, 176, 0.9); background: transparent;")
        title_vlayout.addWidget(subtitle_label)
        
        header_layout.addWidget(title_container)
        content_layout.addLayout(header_layout)
        
        content_layout.addSpacing(16)
        
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("background: transparent;")
        
        self._create_license_panel()
        self._create_progress_panel()
        
        self.stacked_widget.setCurrentIndex(1)
        
        content_layout.addWidget(self.stacked_widget)
        
        content_layout.addStretch()
        
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        
        self.copyright_label = QLabel("Automated Trading Platform")
        self.copyright_label.setFont(QFont("Segoe UI", 9))
        self.copyright_label.setStyleSheet("color: rgba(74, 85, 104, 0.7); background: transparent;")
        footer_layout.addWidget(self.copyright_label)
        
        footer_layout.addStretch()
        
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setFont(QFont("Segoe UI Semibold", 9))
        version_label.setStyleSheet("""
            color: rgba(79, 172, 254, 0.8);
            background: rgba(79, 172, 254, 0.1);
            padding: 4px 10px;
            border-radius: 10px;
        """)
        footer_layout.addWidget(version_label)
        
        content_layout.addLayout(footer_layout)
        
        container_layout.addWidget(content_widget)
        
        main_layout.addWidget(container)
        
        self._install_drag_filter(container)

    def eventFilter(self, obj, event):
        """Intercept mouse events from all child widgets for window dragging"""
        if isinstance(obj, QLineEdit):
            return False
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            return True
        elif event.type() == QEvent.MouseMove and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            return True
        elif event.type() == QEvent.MouseButtonRelease:
            self._drag_pos = None
            return True
        return super().eventFilter(obj, event)

    def _install_drag_filter(self, widget):
        """Recursively install event filter on widget and its children for drag support"""
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            if not isinstance(child, (QPushButton, QLineEdit)):
                child.installEventFilter(self)

    def _create_license_panel(self):
        """Create the license activation panel"""
        license_panel = QWidget()
        license_panel.setObjectName("licensePanel")
        license_layout = QVBoxLayout(license_panel)
        license_layout.setContentsMargins(0, 0, 0, 0)
        license_layout.setSpacing(15)
        
        glass_panel = QFrame()
        glass_panel.setObjectName("glassPanel")
        glass_panel.setStyleSheet("""
            #glassPanel {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        glass_layout = QVBoxLayout(glass_panel)
        glass_layout.setContentsMargins(24, 20, 24, 20)
        glass_layout.setSpacing(14)
        
        self.license_title = QLabel("License Activation")
        self.license_title.setFont(QFont("Segoe UI Semibold", 13))
        self.license_title.setAlignment(Qt.AlignCenter)
        self.license_title.setStyleSheet("color: #4facfe; background: transparent;")
        glass_layout.addWidget(self.license_title)
        
        self.license_message = QLabel("Enter your license key or start a free trial")
        self.license_message.setFont(QFont("Segoe UI", 10))
        self.license_message.setAlignment(Qt.AlignCenter)
        self.license_message.setWordWrap(True)
        self.license_message.setStyleSheet("color: #a0aec0; background: transparent;")
        glass_layout.addWidget(self.license_message)
        
        self.license_input = QLineEdit()
        self.license_input.setPlaceholderText("Enter license key (BTF-XXXX-XXXX-XXXX)")
        self.license_input.setContextMenuPolicy(Qt.DefaultContextMenu)
        license_font = QFont()
        license_font.setStyleHint(QFont.Monospace)
        license_font.setPointSize(11)
        self.license_input.setFont(license_font)
        self.license_input.setAlignment(Qt.AlignCenter)
        self.license_input.setFixedHeight(44)
        self.license_input.setStyleSheet("""
            QLineEdit {
                background: rgba(45, 55, 72, 0.6);
                border: 1px solid rgba(79, 172, 254, 0.3);
                border-radius: 10px;
                color: #e2e8f0;
                padding: 8px 15px;
                selection-background-color: rgba(79, 172, 254, 0.4);
                selection-color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid rgba(79, 172, 254, 0.7);
                background: rgba(45, 55, 72, 0.8);
            }
            QLineEdit::placeholder {
                color: rgba(160, 174, 192, 0.5);
            }
        """)
        glass_layout.addWidget(self.license_input)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        self.trial_button = QPushButton("Start Free Trial")
        self.trial_button.setFont(QFont("Segoe UI Semibold", 10))
        self.trial_button.setFixedHeight(40)
        self.trial_button.setCursor(Qt.PointingHandCursor)
        self.trial_button.setStyleSheet("""
            QPushButton {
                background: rgba(72, 187, 120, 0.2);
                border: 1px solid rgba(72, 187, 120, 0.5);
                border-radius: 10px;
                color: #48bb78;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: rgba(72, 187, 120, 0.3);
                border: 1px solid rgba(72, 187, 120, 0.7);
            }
            QPushButton:pressed {
                background: rgba(72, 187, 120, 0.4);
            }
            QPushButton:disabled {
                background: rgba(45, 55, 72, 0.4);
                color: rgba(160, 174, 192, 0.5);
                border: 1px solid rgba(160, 174, 192, 0.2);
            }
        """)
        button_layout.addWidget(self.trial_button)
        
        self.activate_button = QPushButton("Activate License")
        self.activate_button.setFont(QFont("Segoe UI Semibold", 10))
        self.activate_button.setFixedHeight(40)
        self.activate_button.setCursor(Qt.PointingHandCursor)
        self.activate_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(79, 172, 254, 0.3), stop:1 rgba(0, 242, 254, 0.3));
                border: 1px solid rgba(79, 172, 254, 0.5);
                border-radius: 10px;
                color: #4facfe;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(79, 172, 254, 0.4), stop:1 rgba(0, 242, 254, 0.4));
                border: 1px solid rgba(79, 172, 254, 0.7);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(79, 172, 254, 0.5), stop:1 rgba(0, 242, 254, 0.5));
            }
            QPushButton:disabled {
                background: rgba(45, 55, 72, 0.4);
                color: rgba(160, 174, 192, 0.5);
                border: 1px solid rgba(160, 174, 192, 0.2);
            }
        """)
        button_layout.addWidget(self.activate_button)
        
        glass_layout.addLayout(button_layout)
        
        self.license_status = QLabel("")
        self.license_status.setFont(QFont("Segoe UI", 9))
        self.license_status.setAlignment(Qt.AlignCenter)
        self.license_status.setWordWrap(True)
        self.license_status.setStyleSheet("color: #fc8181; background: transparent;")
        self.license_status.hide()
        glass_layout.addWidget(self.license_status)
        
        license_layout.addWidget(glass_panel)
        
        self.stacked_widget.addWidget(license_panel)
    
    def _create_progress_panel(self):
        """Create the startup progress panel"""
        progress_panel = QWidget()
        progress_panel.setObjectName("progressPanel")
        progress_layout = QVBoxLayout(progress_panel)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(15)
        
        glass_panel = QFrame()
        glass_panel.setObjectName("glassPanel")
        glass_panel.setStyleSheet("""
            #glassPanel {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        glass_layout = QVBoxLayout(glass_panel)
        glass_layout.setContentsMargins(24, 20, 24, 20)
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
                    stop:0 #4facfe, stop:0.5 #00f2fe, stop:1 #4facfe);
                border-radius: 3px;
            }
        """)
        glass_layout.addWidget(self.progress_bar)
        
        progress_layout.addWidget(glass_panel)
        
        self.stacked_widget.addWidget(progress_panel)
    
    def _connect_signals(self):
        """Connect all signals"""
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
        """Called when splash screen is shown - trigger license check immediately"""
        super().showEvent(event)
        
        if not self._license_check_started:
            self._license_check_started = True
            QTimer.singleShot(50, self._auto_license_check)
    
    def _auto_license_check(self):
        """Automatically check for existing license when splash is shown"""
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
                self.license_rejected = True
                self._show_license_panel()
    
    def start_license_check(self):
        """Start the license validation process"""
        if self.skip_license:
            self._show_progress_panel()
            self.startup_ready.emit()
            return
        
        license_key = os.getenv('LICENSE_KEY', '').strip()
        if license_key and self.license_controller:
            self._show_validating()
            self.license_controller.check_existing_license()
        elif license_key:
            self._show_progress_panel()
            self.license_info.setText(f"License: Active")
            self.startup_ready.emit()
        else:
            self._show_license_panel()
    
    def _show_license_panel(self):
        """Show the license activation panel"""
        self.stacked_widget.setCurrentIndex(0)
        self.setFixedSize(540, 440)
        self.license_input.setFocus()
    
    def _show_progress_panel(self):
        """Show the startup progress panel"""
        self.stacked_widget.setCurrentIndex(1)
        self.setFixedSize(540, 360)
    
    def _show_validating(self):
        """Show validating state"""
        self.license_message.setText("Validating license...")
        self.license_input.setEnabled(False)
        self.trial_button.setEnabled(False)
        self.activate_button.setEnabled(False)
        self.license_status.hide()
    
    def _on_trial_clicked(self):
        """Handle trial button click"""
        if self.license_controller:
            self._show_validating()
            self.license_controller.request_trial()
        else:
            self._show_status("Trial not available", error=True)
    
    def _on_activate_clicked(self):
        """Handle activate button click"""
        license_key = self.license_input.text().strip()
        if not license_key:
            self._show_status("Please enter a license key", error=True)
            return
        
        if self.license_controller:
            self._show_validating()
            self.license_controller.activate_license(license_key)
        else:
            os.environ['LICENSE_KEY'] = license_key
            self._on_license_activated({'days_remaining': 365, 'license_type': 'manual'})
    
    def _on_license_state_changed(self, state, message: str):
        """Handle license state changes"""
        if state == LicenseState.VALIDATING:
            self.status_label.setText("Validating license...")
        elif state == LicenseState.ACTIVATED or state == LicenseState.OFFLINE_GRACE:
            self.status_label.setText("License valid - starting...")
            self._show_progress_panel()
            QTimer.singleShot(0, self.startup_ready.emit)
        elif state == LicenseState.REQUIRE_KEY:
            self.license_rejected = True
            self._show_license_panel()
            self.license_input.setEnabled(True)
            self.trial_button.setEnabled(True)
            self.activate_button.setEnabled(True)
            if message:
                self._show_status(message, error=True)
        elif state == LicenseState.EXPIRED:
            self.license_rejected = True
            self._show_license_panel()
            self.license_title.setText("License Expired")
            self.license_title.setStyleSheet("color: #fc8181; background: transparent;")
            self.license_message.setText("Your license has expired. Please renew or enter a new key.")
            self.license_input.setEnabled(True)
            self.trial_button.setEnabled(False)
            self.activate_button.setEnabled(True)
    
    def _on_license_activated(self, license_data: dict):
        """Handle successful license activation"""
        self.license_rejected = False
        self.license_validated_ok = True
        days = license_data.get('days_remaining', 0)
        license_type = license_data.get('license_type', 'subscription').title()
        
        self._save_license_to_database(license_data)
        
        self.license_info.setText(f"{license_type} License - {days} days remaining")
        self._show_progress_panel()
        self.license_validated.emit(license_data)
        self.startup_ready.emit()
    
    def _save_license_to_database(self, license_data: dict):
        """Save the activated license to database for persistence across restarts"""
        try:
            license_key = license_data.get('license_key', '')
            if not license_key and self.license_controller and hasattr(self.license_controller, '_client'):
                cache = self.license_controller._client._load_cache() if self.license_controller._client else None
                if cache:
                    license_key = cache.get('license_key', '')
            
            if not license_key:
                license_key = os.getenv('LICENSE_KEY', '')
            
            if not license_key:
                print("[SPLASH] Warning: No license key to save to database")
                return
            
            machine_id = ''
            if self.license_controller and hasattr(self.license_controller, '_client') and self.license_controller._client:
                machine_id = self.license_controller._client.machine_id
            
            try:
                from gui_app.database import save_local_license
                save_local_license(license_key, machine_id, license_data)
                print(f"[SPLASH] ✓ License saved to database")
            except ImportError:
                print("[SPLASH] Warning: Database not available for license storage")
            except Exception as e:
                print(f"[SPLASH] Warning: Could not save license to database: {e}")
        except Exception as e:
            print(f"[SPLASH] Error saving license: {e}")
    
    def _on_license_failed(self, error: str):
        """Handle license validation failure"""
        self._show_license_panel()
        self.license_input.setEnabled(True)
        self.trial_button.setEnabled(True)
        self.activate_button.setEnabled(True)
        self._show_status(error, error=True)
    
    def _on_require_input(self, message: str):
        """Handle license input required"""
        self._show_license_panel()
        self.license_input.setEnabled(True)
        self.trial_button.setEnabled(True)
        self.activate_button.setEnabled(True)
        if message:
            self.license_message.setText(message)
    
    def _show_status(self, message: str, error: bool = False):
        """Show status message"""
        self.license_status.setText(message)
        if error:
            self.license_status.setStyleSheet("color: #fc8181; background: transparent;")
        else:
            self.license_status.setStyleSheet("color: #48bb78; background: transparent;")
        self.license_status.show()
    
    def _on_progress_update(self, percent: int, message: str):
        """Handle progress updates"""
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)
    
    def _on_startup_complete(self):
        """Handle startup completion"""
        self.progress_bar.setValue(100)
        self.status_label.setText("Ready!")
        self.status_label.setStyleSheet("color: #48bb78; background: transparent;")
        QTimer.singleShot(400, self.close)
    
    def _on_startup_failed(self, error: str):
        """Handle startup failure"""
        self.status_label.setText(f"Error: {error}")
        self.status_label.setStyleSheet("color: #fc8181; background: transparent;")
        QTimer.singleShot(3000, self.close)
    
    def set_progress(self, percent: int, message: str = ""):
        """Manually set progress"""
        self.progress_bar.setValue(percent)
        if message:
            self.status_label.setText(message)
    
    def paintEvent(self, event):
        """Custom paint for additional effects"""
        super().paintEvent(event)


def show_splash_with_license(progress_reporter: Optional[StartupProgress] = None) -> SplashScreen:
    """
    Show splash screen with license validation.
    Returns the splash widget. Wait for startup_ready signal before proceeding.
    """
    splash = SplashScreen(progress_reporter)
    splash.show()
    QApplication.processEvents()
    splash.start_license_check()
    return splash


def show_splash_screen(progress_reporter: Optional[StartupProgress] = None) -> SplashScreen:
    """
    Show the splash screen and return the widget.
    Call splash.close() when startup is complete.
    """
    splash = SplashScreen(progress_reporter, skip_license=True)
    splash.show()
    splash._show_progress_panel()
    QApplication.processEvents()
    return splash


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    progress = StartupProgress()
    splash = show_splash_with_license(progress)
    
    def on_startup_ready():
        print("License validated, starting app...")
        
        def simulate_startup():
            steps = [
                (1, "Loading configuration..."),
                (2, "Initializing database..."),
                (3, "Connecting to Discord..."),
                (4, "Connecting to Telegram..."),
                (5, "Initializing Webull broker..."),
                (6, "Initializing Alpaca broker..."),
                (7, "Starting web control panel..."),
                (8, "Loading channels..."),
                (9, "Starting order processor..."),
                (10, "Ready!")
            ]
            
            def update_step(index):
                if index < len(steps):
                    step, msg = steps[index]
                    progress.update(step, msg)
                    QTimer.singleShot(400, lambda: update_step(index + 1))
                else:
                    progress.complete()
            
            update_step(0)
        
        QTimer.singleShot(100, simulate_startup)
    
    splash.startup_ready.connect(on_startup_ready)
    
    sys.exit(app.exec())
