"""
BotifyTrades Splash Screen with Progress Bar
Shows loading progress while the bot initializes
"""
import sys
import os
from typing import Optional, Callable
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, 
    QProgressBar, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QBrush, QPen

try:
    from upgrade.version import APP_VERSION
except ImportError:
    APP_VERSION = "3.2.14"


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
    Modern splash screen with progress bar for BotifyTrades startup
    """
    
    def __init__(self, progress_reporter: Optional[StartupProgress] = None):
        super().__init__()
        self.progress_reporter = progress_reporter
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
        
        self.setFixedSize(450, 280)
        
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
                    stop:0 #1a1a2e, stop:0.5 #16213e, stop:1 #0f3460);
                border-radius: 15px;
                border: 2px solid #4a90d9;
            }
        """)
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 5)
        container.setGraphicsEffect(shadow)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(30, 25, 30, 25)
        container_layout.setSpacing(15)
        
        title_label = QLabel("BotifyTrades")
        title_font = QFont("Segoe UI", 28, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #4facfe, stop:1 #00f2fe);
            background: transparent;
        """)
        title_label.setStyleSheet("color: #4facfe; background: transparent;")
        container_layout.addWidget(title_label)
        
        subtitle_label = QLabel("Multi-Platform Trading Automation")
        subtitle_font = QFont("Segoe UI", 11)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet("color: #8892b0; background: transparent;")
        container_layout.addWidget(subtitle_label)
        
        container_layout.addSpacing(20)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #2d3748;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4facfe, stop:1 #00f2fe);
                border-radius: 4px;
            }
        """)
        container_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Initializing...")
        status_font = QFont("Segoe UI", 10)
        self.status_label.setFont(status_font)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #a0aec0; background: transparent;")
        container_layout.addWidget(self.status_label)
        
        container_layout.addStretch()
        
        version_label = QLabel(f"v{APP_VERSION}")
        version_font = QFont("Segoe UI", 9)
        version_label.setFont(version_font)
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: #4a5568; background: transparent;")
        container_layout.addWidget(version_label)
        
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
        QTimer.singleShot(500, self.close)
    
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
        """Custom paint for rounded corners"""
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
                QTimer.singleShot(500, lambda: update_step(index + 1))
            else:
                progress.complete()
        
        update_step(0)
    
    QTimer.singleShot(100, simulate_startup)
    
    sys.exit(app.exec())
