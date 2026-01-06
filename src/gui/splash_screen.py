"""
BotifyTrades Premium Splash Screen
Modern glassmorphism design with brand logo and progress tracking
"""
import sys
import os
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QGraphicsDropShadowEffect, QGraphicsBlurEffect
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QSize
from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QBrush, QPen, QLinearGradient, QFontDatabase

try:
    from upgrade.version import APP_VERSION
except ImportError:
    APP_VERSION = "3.2.14"


def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):
        base_path = Path(getattr(sys, '_MEIPASS', '.'))
    else:
        base_path = Path(__file__).parent.parent.parent
    return str(base_path / relative_path)


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


class SplashScreen(QWidget):
    """
    Premium splash screen with glassmorphism design and brand logo
    """
    
    def __init__(self, progress_reporter: Optional[StartupProgress] = None):
        super().__init__()
        self.progress_reporter = progress_reporter
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the splash screen UI with premium glassmorphism design"""
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint |
            Qt.SplashScreen
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.setFixedSize(520, 340)
        
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
        
        header_layout = QHBoxLayout()
        header_layout.setSpacing(18)
        header_layout.setAlignment(Qt.AlignCenter)
        
        self.logo_label = QLabel()
        logo_path = get_resource_path("gui_app/static/images/logo-icon.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            scaled_pixmap = pixmap.scaled(
                QSize(72, 72), 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            self.logo_label.setPixmap(scaled_pixmap)
        else:
            self.logo_label.setText("BT")
            self.logo_label.setStyleSheet("""
                color: #4facfe;
                font-size: 32px;
                font-weight: bold;
                background: rgba(79, 172, 254, 0.15);
                border-radius: 18px;
                padding: 12px;
            """)
        
        self.logo_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(79, 172, 254, 0.25),
                stop:0.5 rgba(0, 242, 254, 0.15),
                stop:1 rgba(79, 172, 254, 0.25));
            border-radius: 18px;
            padding: 8px;
            border: 1px solid rgba(79, 172, 254, 0.3);
        """)
        
        logo_shadow = QGraphicsDropShadowEffect()
        logo_shadow.setBlurRadius(25)
        logo_shadow.setColor(QColor(79, 172, 254, 100))
        logo_shadow.setOffset(0, 4)
        self.logo_label.setGraphicsEffect(logo_shadow)
        
        header_layout.addWidget(self.logo_label)
        
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        
        title_label = QLabel("BotifyTrades")
        title_label.setFont(QFont("Segoe UI", 32, QFont.Bold))
        title_label.setStyleSheet("""
            color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #4facfe, stop:0.5 #00f2fe, stop:1 #4facfe);
            background: transparent;
            letter-spacing: -1px;
        """)
        title_label.setStyleSheet("color: #4facfe; background: transparent; letter-spacing: -1px;")
        title_layout.addWidget(title_label)
        
        subtitle_label = QLabel("Multi-Platform Trading Automation")
        subtitle_label.setFont(QFont("Segoe UI", 11, QFont.Normal))
        subtitle_label.setStyleSheet("color: rgba(136, 146, 176, 0.9); background: transparent;")
        title_layout.addWidget(subtitle_label)
        
        header_layout.addWidget(title_container)
        container_layout.addLayout(header_layout)
        
        container_layout.addSpacing(25)
        
        glass_panel = QWidget()
        glass_panel.setObjectName("glassPanel")
        glass_panel.setStyleSheet("""
            #glassPanel {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        glass_layout = QVBoxLayout(glass_panel)
        glass_layout.setContentsMargins(20, 18, 20, 18)
        glass_layout.setSpacing(12)
        
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
        
        container_layout.addWidget(glass_panel)
        
        container_layout.addStretch()
        
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        
        copyright_label = QLabel("Automated Trading Platform")
        copyright_label.setFont(QFont("Segoe UI", 9))
        copyright_label.setStyleSheet("color: rgba(74, 85, 104, 0.7); background: transparent;")
        footer_layout.addWidget(copyright_label)
        
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
        
        container_layout.addLayout(footer_layout)
        
        main_layout.addWidget(container)
    
    def _connect_signals(self):
        """Connect progress reporter signals"""
        if self.progress_reporter:
            self.progress_reporter.progress_updated.connect(self._on_progress_update)
            self.progress_reporter.startup_complete.connect(self._on_startup_complete)
            self.progress_reporter.startup_failed.connect(self._on_startup_failed)
    
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


def show_splash_screen(progress_reporter: Optional[StartupProgress] = None) -> SplashScreen:
    """
    Show the splash screen and return the widget.
    Call splash.close() when startup is complete.
    """
    splash = SplashScreen(progress_reporter)
    splash.show()
    QApplication.processEvents()
    return splash


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    progress = StartupProgress()
    splash = show_splash_screen(progress)
    
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
    
    sys.exit(app.exec())
